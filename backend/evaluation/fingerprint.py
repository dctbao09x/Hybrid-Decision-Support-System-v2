# backend/evaluation/fingerprint.py
"""
Dataset Fingerprint
===================
Computes a unique fingerprint for the training dataset to:
  • Track data changes between runs
  • Detect data drift
  • Ensure reproducibility

Fingerprint includes:
  • SHA256 hash of the entire CSV
  • Row count
  • Column schema (name → dtype)
  • Null ratios per column
  • Feature statistics (min, max, mean, std)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("ml_evaluation.fingerprint")


@dataclass
class DatasetFingerprint:
    """
    Immutable fingerprint of a dataset.

    Attributes:
        hash:           SHA256 hash of the raw CSV file.
        rows:           Number of rows.
        columns:        Number of columns.
        schema:         Dict mapping column name → dtype string.
        null_ratio:     Dict mapping column name → ratio of nulls (0.0-1.0).
        feature_stats:  Dict of feature statistics (numeric columns only).
        created_at:     ISO timestamp when fingerprint was computed.
        source_path:    Original file path.
    """
    hash: str
    rows: int
    columns: int
    schema: Dict[str, str]
    null_ratio: Dict[str, float]
    feature_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    label_distribution: Dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    source_path: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "hash": self.hash,
            "rows": self.rows,
            "columns": self.columns,
            "schema": self.schema,
            "null_ratio": self.null_ratio,
            "feature_stats": self.feature_stats,
            "label_distribution": self.label_distribution,
            "created_at": self.created_at,
            "source_path": self.source_path,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatasetFingerprint":
        """Deserialize from dictionary."""
        return cls(
            hash=data["hash"],
            rows=data["rows"],
            columns=data["columns"],
            schema=data["schema"],
            null_ratio=data["null_ratio"],
            feature_stats=data.get("feature_stats", {}),
            label_distribution=data.get("label_distribution", {}),
            created_at=data.get("created_at", ""),
            source_path=data.get("source_path", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "DatasetFingerprint":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def matches(self, other: "DatasetFingerprint") -> bool:
        """Check if two fingerprints have the same hash."""
        return self.hash == other.hash

    def schema_matches(self, other: "DatasetFingerprint") -> bool:
        """Check if schemas are identical."""
        return self.schema == other.schema


class FingerprintGenerator:
    """
    Generates fingerprints for CSV datasets.

    Usage::

        gen = FingerprintGenerator()
        fp = gen.compute("data/training.csv")
        print(fp.hash, fp.rows, fp.schema)
    """

    def __init__(self, target_column: str = "target_career"):
        self._target_column = target_column

    def compute(self, path: str) -> DatasetFingerprint:
        """
        Compute fingerprint for a CSV file.

        Args:
            path: Path to the CSV file.

        Returns:
            DatasetFingerprint with all computed fields.
        """
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        logger.info("Computing fingerprint for %s", path)

        # 1. Compute SHA256 of raw file
        file_hash = self._compute_hash(path_obj)

        # 2. Load DataFrame for analysis
        df = pd.read_csv(path_obj)

        # 3. Schema
        schema = {col: str(dtype) for col, dtype in df.dtypes.items()}

        # 4. Null ratios
        null_ratio = {
            col: round(df[col].isnull().sum() / len(df), 6)
            for col in df.columns
        }

        # 5. Feature statistics (numeric columns only)
        feature_stats = {}
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            feature_stats[col] = {
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "mean": round(float(df[col].mean()), 6),
                "std": round(float(df[col].std()), 6),
                "median": float(df[col].median()),
            }

        # 6. Label distribution (if target column exists)
        label_distribution = {}
        if self._target_column in df.columns:
            label_distribution = df[self._target_column].value_counts().to_dict()

        fingerprint = DatasetFingerprint(
            hash=file_hash,
            rows=len(df),
            columns=len(df.columns),
            schema=schema,
            null_ratio=null_ratio,
            feature_stats=feature_stats,
            label_distribution=label_distribution,
            source_path=str(path_obj.resolve()),
        )

        logger.info(
            "Fingerprint: hash=%s rows=%d cols=%d",
            file_hash[:16], fingerprint.rows, fingerprint.columns,
        )

        return fingerprint

    def _compute_hash(self, path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def save_fingerprint(self, fingerprint: DatasetFingerprint, path: str) -> None:
        """Save fingerprint to JSON file."""
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as f:
            f.write(fingerprint.to_json())
        logger.info("Saved fingerprint → %s", path)

    def load_fingerprint(self, path: str) -> DatasetFingerprint:
        """Load fingerprint from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return DatasetFingerprint.from_json(f.read())
