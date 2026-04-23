from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List

from backend.feedback.storage import get_feedback_storage
from backend.feedback.governance import ComplianceChecker

logger = logging.getLogger(__name__)


@dataclass
class DatasetRecord:
    dataset_id: str
    source: str
    hash: str
    kb_version: str
    created_at: str
    size: int
    path: str
    avg_quality_score: float = 0.0
    min_quality_score: float = 0.0
    label_classes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source": self.source,
            "hash": self.hash,
            "kb_version": self.kb_version,
            "created_at": self.created_at,
            "size": self.size,
            "path": self.path,
            "avg_quality_score": self.avg_quality_score,
            "min_quality_score": self.min_quality_score,
            "label_classes": self.label_classes,
        }


class DatasetStore:
    REQUIRED_COLUMNS = ["math_score", "physics_score", "interest_it", "logic_score", "target_career"]

    def __init__(self, base_path: str = "storage/mlops/datasets"):
        self._root = Path(__file__).resolve().parents[2]
        self._base = self._root / base_path
        self._index_path = self._base / "index.json"
        self._base.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self._index_path.exists():
            self._write_index({"datasets": [], "updated_at": datetime.now(timezone.utc).isoformat()})

    def _read_index(self) -> Dict[str, Any]:
        with self._index_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_index(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._index_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    async def build_immutable_from_training_candidates(
        self,
        source: str = "feedback",
        min_quality: float = 0.0,
        limit: int = 5000,
        skip_governance: bool = False,
    ) -> DatasetRecord:
        storage = get_feedback_storage()
        await storage.initialize()

        compliance = ComplianceChecker(storage)
        check = await compliance.run_compliance_check()
        if check.get("status") != "passed":
            issues = check.get("issues", [])
            if skip_governance:
                # Admin/manual trigger: log issues but do not block training
                logger.warning(
                    "Governance check has issues (skipped for %s trigger): %s",
                    source,
                    [{"type": i.get("type"), "severity": i.get("severity"), "msg": i.get("message")} for i in issues],
                )
            else:
                raise ValueError("Governance check failed")

        candidates = await storage.get_training_candidates(
            min_quality=min_quality,
            unused_only=True,
            limit=limit,
        )
        if not candidates:
            raise ValueError("No eligible training candidates")

        rows: List[Dict[str, Any]] = []
        kb_version = "unknown"
        quality_scores: List[float] = []
        labels: set[str] = set()
        for cand in candidates:
            f = cand.input_features or {}
            try:
                row = {
                    "math_score": float(f.get("math_score", 0.0)),
                    "physics_score": float(f.get("physics_score", 0.0)),
                    "interest_it": float(f.get("interest_it", 0.0)),
                    "logic_score": float(f.get("logic_score", 0.0)),
                    "target_career": str(cand.target_label),
                }
                rows.append(row)
                quality_scores.append(float(getattr(cand, "quality_score", 0.0) or 0.0))
                labels.add(str(cand.target_label))
                if cand.kb_version:
                    kb_version = cand.kb_version
            except Exception:
                continue

        if not rows:
            raise ValueError("No usable training candidates after normalization")

        csv_buffer = "\n".join(
            [",".join(self.REQUIRED_COLUMNS)]
            + [",".join(str(r[c]) for c in self.REQUIRED_COLUMNS) for r in rows]
        )
        dataset_hash = hashlib.sha256(csv_buffer.encode("utf-8")).hexdigest()
        created = datetime.now(timezone.utc).isoformat()
        dataset_id = f"ds_{created.replace(':', '').replace('-', '').replace('.', '')}_{dataset_hash[:8]}"
        out_path = self._base / f"{dataset_id}.csv"

        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        record = DatasetRecord(
            dataset_id=dataset_id,
            source=source,
            hash=dataset_hash,
            kb_version=kb_version,
            created_at=created,
            size=len(rows),
            path=str(out_path),
            avg_quality_score=(sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0,
            min_quality_score=min(quality_scores) if quality_scores else 0.0,
            label_classes=len(labels),
        )

        with self._lock:
            index = self._read_index()
            index["datasets"].append(record.to_dict())
            self._write_index(index)

        train_ids = [c.train_id for c in candidates]
        await storage.mark_candidates_used(train_ids, batch_id=dataset_id)
        return record

    def list_datasets(self) -> List[Dict[str, Any]]:
        return sorted(self._read_index().get("datasets", []), key=lambda x: x.get("created_at", ""), reverse=True)

    def get_dataset(self, dataset_id: str) -> Dict[str, Any] | None:
        for row in self._read_index().get("datasets", []):
            if row.get("dataset_id") == dataset_id:
                return row
        return None
