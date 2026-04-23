# backend/retrain/dataset_builder.py
"""
Dataset Builder
===============

Builds training dataset by merging offline and online data sources.

Responsibilities:
  - Load base training data (offline)
  - Append feedback data (online)
  - Deduplicate
  - Validate schema
  - Export for training
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger("ml_retrain.dataset")


@dataclass
class DatasetStats:
    """Statistics about the built dataset."""
    total_rows: int
    offline_rows: int
    online_rows: int
    deduplicated_rows: int
    columns: List[str]
    label_distribution: Dict[str, int]
    hash: str
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "offline_rows": self.offline_rows,
            "online_rows": self.online_rows,
            "deduplicated_rows": self.deduplicated_rows,
            "columns": self.columns,
            "label_distribution": self.label_distribution,
            "hash": self.hash,
            "timestamp": self.timestamp,
        }


class DatasetBuilder:
    """
    Builds combined training dataset from multiple sources.
    
    Usage::
    
        builder = DatasetBuilder()
        builder.load_offline("data/training.csv")
        builder.load_online_feedback("feedback_logs/matched.jsonl")
        
        df, stats = builder.build()
        builder.export("data/training_combined.csv")
    """
    
    REQUIRED_COLUMNS = ["math_score", "physics_score", "interest_it", "logic_score", "target_career"]
    
    def __init__(self):
        self._project_root = Path(__file__).resolve().parents[2]
        
        self._offline_data: Optional[pd.DataFrame] = None
        self._online_data: List[Dict[str, Any]] = []
        self._combined: Optional[pd.DataFrame] = None
        self._stats: Optional[DatasetStats] = None
        
        # Deduplication tracking
        self._seen_hashes: Set[str] = set()
    
    def load_offline(self, path: str) -> int:
        """
        Load offline training data from CSV.
        
        Returns:
            Number of rows loaded
        """
        full_path = self._project_root / path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Offline data not found: {full_path}")
        
        self._offline_data = pd.read_csv(full_path)
        
        # Validate columns
        missing = set(self.REQUIRED_COLUMNS) - set(self._offline_data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        logger.info("Loaded %d offline samples from %s", len(self._offline_data), path)
        return len(self._offline_data)
    
    def load_online_feedback(
        self,
        path: str = "feedback_logs/matched.jsonl",
        use_actual: bool = True,
    ) -> int:
        """
        Load online feedback data.
        
        Args:
            path: Path to feedback JSONL file
            use_actual: If True, use actual_career as label (verified feedback)
                       If False, use predicted_career (pseudo-labeling)
        
        Returns:
            Number of records loaded
        """
        full_path = self._project_root / path
        
        if not full_path.exists():
            logger.warning("No feedback file found: %s", full_path)
            return 0
        
        count = 0
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    
                    # Extract features
                    features = record.get("features", {})
                    
                    # Choose label
                    if use_actual:
                        label = record.get("actual_career")
                    else:
                        label = record.get("predicted_career")
                    
                    if not label or not features:
                        continue
                    
                    self._online_data.append({
                        "math_score": features.get("math_score", 0),
                        "physics_score": features.get("physics_score", 0),
                        "interest_it": features.get("interest_it", 0),
                        "logic_score": features.get("logic_score", 0),
                        "target_career": label,
                        "_source": "online_feedback",
                    })
                    count += 1
                    
                except (json.JSONDecodeError, KeyError):
                    continue
        
        logger.info("Loaded %d online feedback samples", count)
        return count
    
    def build(self, deduplicate: bool = True) -> Tuple[pd.DataFrame, DatasetStats]:
        """
        Build combined dataset.
        
        Args:
            deduplicate: If True, remove duplicate rows
        
        Returns:
            (DataFrame, DatasetStats)
        """
        # Start with offline data
        if self._offline_data is not None:
            offline_df = self._offline_data.copy()
            offline_df["_source"] = "offline"
            offline_count = len(offline_df)
        else:
            offline_df = pd.DataFrame(columns=self.REQUIRED_COLUMNS + ["_source"])
            offline_count = 0
        
        # Add online data
        online_count = len(self._online_data)
        if self._online_data:
            online_df = pd.DataFrame(self._online_data)
        else:
            online_df = pd.DataFrame(columns=self.REQUIRED_COLUMNS + ["_source"])
        
        # Combine
        self._combined = pd.concat([offline_df, online_df], ignore_index=True)
        
        # Deduplicate
        pre_dedup = len(self._combined)
        if deduplicate:
            self._combined = self._deduplicate(self._combined)
        dedup_removed = pre_dedup - len(self._combined)
        
        # Compute stats
        self._stats = self._compute_stats(
            offline_count=offline_count,
            online_count=online_count,
            dedup_removed=dedup_removed,
        )
        
        logger.info(
            "Built dataset: %d total (%d offline + %d online - %d duplicates)",
            self._stats.total_rows,
            offline_count,
            online_count,
            dedup_removed,
        )
        
        return self._combined, self._stats
    
    def export(self, path: str) -> str:
        """
        Export combined dataset to CSV.
        
        Returns:
            Full path to exported file
        """
        if self._combined is None:
            raise ValueError("No dataset built. Call build() first.")
        
        full_path = self._project_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Export without _source column
        export_df = self._combined.drop(columns=["_source"], errors="ignore")
        export_df.to_csv(full_path, index=False)
        
        logger.info("Exported dataset to %s", full_path)
        return str(full_path)
    
    def get_stats(self) -> Optional[DatasetStats]:
        """Get dataset statistics."""
        return self._stats
    
    def _deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate rows based on features."""
        # Create row hash for deduplication
        feature_cols = [c for c in self.REQUIRED_COLUMNS if c != "target_career"]
        
        def row_hash(row):
            values = [str(row[c]) for c in feature_cols] + [str(row["target_career"])]
            return hashlib.md5("|".join(values).encode()).hexdigest()
        
        df["_hash"] = df.apply(row_hash, axis=1)
        df = df.drop_duplicates(subset=["_hash"], keep="first")
        df = df.drop(columns=["_hash"])
        
        return df
    
    def _compute_stats(
        self,
        offline_count: int,
        online_count: int,
        dedup_removed: int,
    ) -> DatasetStats:
        """Compute dataset statistics."""
        # Label distribution
        label_dist = self._combined["target_career"].value_counts().to_dict()
        
        # Compute hash
        hash_str = hashlib.sha256(
            self._combined.to_csv(index=False).encode()
        ).hexdigest()
        
        return DatasetStats(
            total_rows=len(self._combined),
            offline_rows=offline_count,
            online_rows=online_count,
            deduplicated_rows=dedup_removed,
            columns=list(self._combined.columns),
            label_distribution=label_dist,
            hash=hash_str,
        )
