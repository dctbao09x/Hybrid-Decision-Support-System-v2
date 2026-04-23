from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


@dataclass(frozen=True)
class RetrainGovernanceConfig:
    min_dataset_rows: int
    min_avg_quality: float
    min_label_classes: int
    min_candidate_quality: float
    manual_approval_required: bool
    approval_ttl_hours: float
    cooldown_bypass_requires_approval: bool
    rollback_max_per_24h: int
    rollback_allowed_reasons: Tuple[str, ...]
    deploy_min_accuracy: float
    deploy_min_f1: float

    @classmethod
    def from_env(cls) -> "RetrainGovernanceConfig":
        raw_reasons = os.getenv(
            "MLOPS_ROLLBACK_ALLOWED_REASONS",
            "auto_guard,manual,model_regression,drift_alert,incident_response",
        )
        reasons = tuple(
            sorted({part.strip().lower() for part in raw_reasons.split(",") if part.strip()})
        )
        if not reasons:
            reasons = ("manual",)

        return cls(
            min_dataset_rows=max(1, _env_int("MLOPS_RETRAIN_MIN_DATASET_ROWS", 50)),
            min_avg_quality=max(0.0, min(1.0, _env_float("MLOPS_RETRAIN_MIN_AVG_QUALITY", 0.6))),
            min_label_classes=max(1, _env_int("MLOPS_RETRAIN_MIN_LABEL_CLASSES", 2)),
            min_candidate_quality=max(0.0, min(1.0, _env_float("MLOPS_RETRAIN_MIN_CANDIDATE_QUALITY", 0.5))),
            manual_approval_required=_env_bool("MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED", True),
            approval_ttl_hours=max(0.5, _env_float("MLOPS_RETRAIN_APPROVAL_TTL_HOURS", 8.0)),
            cooldown_bypass_requires_approval=_env_bool("MLOPS_COOLDOWN_BYPASS_REQUIRES_APPROVAL", True),
            rollback_max_per_24h=max(1, _env_int("MLOPS_ROLLBACK_MAX_PER_24H", 3)),
            rollback_allowed_reasons=reasons,
            deploy_min_accuracy=max(0.0, min(1.0, _env_float("MLOPS_DEPLOY_MIN_ACCURACY", 0.85))),
            deploy_min_f1=max(0.0, min(1.0, _env_float("MLOPS_DEPLOY_MIN_F1", 0.82))),
        )


class RetrainApprovalStore:
    """Persistent approval workflow store for manual retraining triggers."""

    def __init__(self, path: str = "storage/mlops/retrain_approvals.json"):
        self._root = Path(__file__).resolve().parents[2]
        self._path = self._root / path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self._path.exists():
            self._write({"approvals": [], "updated_at": _utc_now_iso()})

    def _read(self) -> Dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = _utc_now_iso()
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def request(
        self,
        trigger: str,
        requested_by: str,
        reason: str,
        allow_cooldown_bypass: bool,
        ttl_hours: float,
    ) -> Dict[str, Any]:
        now = _utc_now()
        expires = now + timedelta(hours=max(ttl_hours, 0.5))
        row = {
            "approval_id": uuid.uuid4().hex,
            "trigger": str(trigger or "manual").lower(),
            "requested_by": str(requested_by or "unknown"),
            "reason": str(reason or "manual retrain request"),
            "allow_cooldown_bypass": bool(allow_cooldown_bypass),
            "status": "pending",
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "approved_at": None,
            "approver_id": None,
            "approver_comment": None,
            "consumed": False,
            "consumed_at": None,
        }
        with self._lock:
            payload = self._read()
            approvals = list(payload.get("approvals", []))
            approvals.append(row)
            payload["approvals"] = approvals[-1000:]
            self._write(payload)
        return row

    def approve(
        self,
        approval_id: str,
        approver_id: str,
        approver_comment: Optional[str] = None,
        allow_cooldown_bypass: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            payload = self._read()
            approvals = list(payload.get("approvals", []))
            target: Optional[Dict[str, Any]] = None
            now = _utc_now()
            for row in approvals:
                if str(row.get("approval_id")) != str(approval_id):
                    continue
                target = row
                expires_at = _parse_iso(row.get("expires_at"))
                if expires_at is not None and expires_at <= now:
                    row["status"] = "expired"
                    row["approver_comment"] = row.get("approver_comment") or "expired before approval"
                    break
                if row.get("consumed"):
                    break
                row["status"] = "approved"
                row["approved_at"] = now.isoformat()
                row["approver_id"] = str(approver_id or "unknown")
                if approver_comment is not None:
                    row["approver_comment"] = str(approver_comment)
                if allow_cooldown_bypass is not None:
                    row["allow_cooldown_bypass"] = bool(allow_cooldown_bypass)
                break

            if target is None:
                return None

            payload["approvals"] = approvals
            self._write(payload)
            return dict(target)

    def get(self, approval_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            payload = self._read()
            for row in payload.get("approvals", []):
                if str(row.get("approval_id")) == str(approval_id):
                    return dict(row)
        return None

    def consume(
        self,
        approval_id: str,
        requested_by: str,
        require_cooldown_bypass: bool,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        with self._lock:
            payload = self._read()
            approvals = list(payload.get("approvals", []))
            target: Optional[Dict[str, Any]] = None
            reason = "approval_not_found"
            now = _utc_now()

            for row in approvals:
                if str(row.get("approval_id")) != str(approval_id):
                    continue

                target = row
                status = str(row.get("status", "")).lower()
                if status != "approved":
                    reason = f"approval_status_{status or 'unknown'}"
                    break
                if bool(row.get("consumed")):
                    reason = "approval_already_used"
                    break

                expires_at = _parse_iso(row.get("expires_at"))
                if expires_at is not None and expires_at <= now:
                    row["status"] = "expired"
                    reason = "approval_expired"
                    break

                approver = str(row.get("approver_id") or "").strip()
                if approver and approver == str(requested_by or "").strip():
                    reason = "self_approval_not_allowed"
                    break

                if require_cooldown_bypass and not bool(row.get("allow_cooldown_bypass", False)):
                    reason = "approval_missing_cooldown_bypass_right"
                    break

                row["consumed"] = True
                row["consumed_at"] = now.isoformat()
                row["status"] = "used"
                reason = "approved"
                break

            if target is None:
                return False, reason, None

            payload["approvals"] = approvals
            self._write(payload)
            return reason == "approved", reason, dict(target)


class RetrainAuditLogger:
    """Append-only JSONL audit log for retrain governance actions."""

    def __init__(self, path: str = "storage/mlops/retrain_audit.jsonl"):
        self._root = Path(__file__).resolve().parents[2]
        self._path = self._root / path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def log(
        self,
        event_type: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> None:
        payload = {
            "timestamp": _utc_now_iso(),
            "event_type": str(event_type),
            "status": str(status),
            "run_id": str(run_id) if run_id else None,
            "trigger": str(trigger) if trigger else None,
            "details": details or {},
        }
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return None
