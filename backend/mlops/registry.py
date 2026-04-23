from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional


@dataclass
class RegistryModel:
    model_id: str
    version: str
    dataset_hash: str
    code_hash: str
    metrics: Dict[str, Any]
    status: str
    created_at: str
    artifact_path: str
    reproducibility: Dict[str, Any]
    validation: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "dataset_hash": self.dataset_hash,
            "code_hash": self.code_hash,
            "metrics": self.metrics,
            "status": self.status,
            "created_at": self.created_at,
            "artifact_path": self.artifact_path,
            "reproducibility": self.reproducibility,
            "validation": self.validation,
        }


class ModelRegistryStore:
    def __init__(self, path: str = "storage/mlops/model_registry.json"):
        self._root = Path(__file__).resolve().parents[2]
        self._path = self._root / path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self._path.exists():
            self._write({"models": [], "updated_at": datetime.now(timezone.utc).isoformat()})

    def _read(self) -> Dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def compute_code_hash(self) -> str:
        api_root = self._root / "backend"
        digest = hashlib.sha256()
        for py_file in sorted(api_root.rglob("*.py")):
            digest.update(py_file.name.encode("utf-8"))
            digest.update(py_file.read_bytes())
        return digest.hexdigest()

    def register(self, model: RegistryModel) -> RegistryModel:
        with self._lock:
            data = self._read()
            models = [m for m in data.get("models", []) if m.get("model_id") != model.model_id]
            models.append(model.to_dict())
            data["models"] = models
            self._write(data)
        return model

    def update_validation(self, model_id: str, validation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            target = None
            for row in data.get("models", []):
                if row.get("model_id") == model_id:
                    row["validation"] = validation
                    target = row
                    break
            if target is None:
                return None
            self._write(data)
            return target

    def update_status(self, model_id: str, status: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            target = None
            for row in data.get("models", []):
                if row.get("model_id") == model_id:
                    row["status"] = status
                    target = row
                    break
            if target is None:
                return None
            self._write(data)
            return target

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        for row in data.get("models", []):
            if row.get("model_id") == model_id:
                return row
        return None

    def get_by_version(self, version: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        for row in data.get("models", []):
            if row.get("version") == version:
                return row
        return None

    def list_models(self) -> List[Dict[str, Any]]:
        data = self._read()
        rows = data.get("models", [])
        rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return rows

    def current_prod(self) -> Optional[Dict[str, Any]]:
        for row in self.list_models():
            if row.get("status") == "prod":
                return row
        return None

    def current_staging(self) -> Optional[Dict[str, Any]]:
        for row in self.list_models():
            if row.get("status") == "staging":
                return row
        return None

    def archive_prod_and_set(self, model_id: str, new_status: str = "prod") -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            target = None
            for row in data.get("models", []):
                if row.get("status") == "prod":
                    row["status"] = "archived"
                if row.get("model_id") == model_id:
                    target = row
            if target is None:
                raise ValueError(f"Model not found: {model_id}")
            target["status"] = new_status
            self._write(data)
            return target

    def is_registered_artifact(self, path: Path) -> bool:
        resolved = str(path.resolve())
        for row in self.list_models():
            artifact = Path(row.get("artifact_path", "")).resolve()
            if str(artifact) == resolved:
                return True
        return False
