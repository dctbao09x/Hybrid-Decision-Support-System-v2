from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from backend.mlops.dataset_store import DatasetStore
from backend.mlops.governance import (
    RetrainApprovalStore,
    RetrainAuditLogger,
    RetrainGovernanceConfig,
)
from backend.mlops.registry import ModelRegistryStore, RegistryModel
from backend.mlops.scheduler.policies import CooldownViolation, get_cooldown_policy
from backend.mlops.scheduler.state_store import StateStore, get_state_store
from backend.retrain.trainer import RetrainTrainer
from backend.retrain.validator import RetrainValidator

logger = logging.getLogger(__name__)


_metrics_collector: Optional[Any] = None


def set_mlops_metrics_collector(metrics_collector: Any) -> None:
    global _metrics_collector
    _metrics_collector = metrics_collector


def _metrics_inc(name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.inc(name, value=value, labels=labels)
    except Exception:
        logger.debug("failed to update mlops counter %s", name, exc_info=True)


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, float(value))
    except Exception:
        logger.debug("failed to update mlops gauge %s", name, exc_info=True)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_iso_timestamp(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return None


class MLOpsManager:
    def __init__(self):
        self._root = Path(__file__).resolve().parents[2]
        self._registry = ModelRegistryStore()
        self._datasets = DatasetStore()
        self._trainer = RetrainTrainer()
        self._validator = RetrainValidator()
        self._runs_path = self._root / "storage/mlops/runs.jsonl"
        self._deploy_state_path = self._root / "storage/mlops/deployment_state.json"
        self._monitor_path = self._root / "storage/mlops/monitor_snapshots.jsonl"
        self._shadow_log_path = self._root / "storage/mlops/shadow_results.jsonl"
        self._lock = RLock()
        self._runs_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Cooldown and state management
        self._cooldown_policy = get_cooldown_policy()
        self._state_store = get_state_store()
        self._governance = RetrainGovernanceConfig.from_env()
        self._approvals = RetrainApprovalStore()
        self._audit = RetrainAuditLogger()
        self._metric_state: Dict[str, int] = {
            "retrain_triggers": 0,
            "retrain_successes": 0,
            "bypass_attempts": 0,
            "deploy_successes": 0,
            "rollbacks": 0,
        }
        self._refresh_governance_metrics()
        
        if not self._deploy_state_path.exists():
            self._write_deploy_state({
                "strategy": None,
                "candidate_model_id": None,
                "candidate_version": None,
                "traffic_ratio": 0.0,
                "shadow_enabled": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    def _git_commit(self) -> str:
        try:
            return (
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(self._root), text=True)
                .strip()
            )
        except Exception:
            return "unknown"

    def _append_run(self, run: Dict[str, Any]) -> None:
        with self._runs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(run, ensure_ascii=False) + "\n")

    def _read_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._runs_path.exists():
            return []
        with self._runs_path.open("r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows.reverse()
        return rows[:limit]

    def _write_deploy_state(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._deploy_state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _read_deploy_state(self) -> Dict[str, Any]:
        with self._deploy_state_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _is_manual_trigger(trigger: str) -> bool:
        return str(trigger or "").strip().lower() in {"manual", "admin", "admin_ui"}

    def _audit_event(
        self,
        event_type: str,
        status: str,
        run_id: Optional[str] = None,
        trigger: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._audit.log(
            event_type=event_type,
            status=status,
            run_id=run_id,
            trigger=trigger,
            details=details or {},
        )

    def _refresh_governance_metrics(self) -> None:
        retrain_triggers = float(self._metric_state.get("retrain_triggers", 0))
        retrain_successes = float(self._metric_state.get("retrain_successes", 0))
        bypass_attempts = float(self._metric_state.get("bypass_attempts", 0))
        deploy_successes = float(self._metric_state.get("deploy_successes", 0))
        rollbacks = float(self._metric_state.get("rollbacks", 0))

        retrain_success_rate = retrain_successes / retrain_triggers if retrain_triggers > 0 else 0.0
        bypass_attempt_rate = bypass_attempts / retrain_triggers if retrain_triggers > 0 else 0.0
        rollback_denominator = deploy_successes + rollbacks
        rollback_rate = rollbacks / rollback_denominator if rollback_denominator > 0 else 0.0

        _metrics_set_gauge("retrain_trigger_count", retrain_triggers)
        _metrics_set_gauge("retrain_success_rate", retrain_success_rate)
        _metrics_set_gauge("bypass_attempt_rate", bypass_attempt_rate)
        _metrics_set_gauge("rollback_rate", rollback_rate)

    def _record_retrain_trigger(self, trigger: str, bypass_cooldown: bool) -> None:
        self._metric_state["retrain_triggers"] = int(self._metric_state.get("retrain_triggers", 0)) + 1
        _metrics_inc("retrain_trigger_count")
        if bypass_cooldown:
            self._metric_state["bypass_attempts"] = int(self._metric_state.get("bypass_attempts", 0)) + 1
            _metrics_inc("bypass_attempt_total", labels={"trigger": str(trigger)})
        self._refresh_governance_metrics()

    def _record_retrain_success(self) -> None:
        self._metric_state["retrain_successes"] = int(self._metric_state.get("retrain_successes", 0)) + 1
        self._refresh_governance_metrics()

    def _record_deploy_success(self) -> None:
        self._metric_state["deploy_successes"] = int(self._metric_state.get("deploy_successes", 0)) + 1
        self._refresh_governance_metrics()

    def _record_rollback_success(self) -> None:
        self._metric_state["rollbacks"] = int(self._metric_state.get("rollbacks", 0)) + 1
        self._refresh_governance_metrics()

    def _dataset_quality_gate(self, dataset: Any) -> Dict[str, Any]:
        rows = int(getattr(dataset, "size", 0) or 0)
        avg_quality = _safe_float(getattr(dataset, "avg_quality_score", 0.0), 0.0)
        label_classes = int(getattr(dataset, "label_classes", 0) or 0)

        checks = {
            "min_rows": rows >= int(self._governance.min_dataset_rows),
            "min_avg_quality": avg_quality >= float(self._governance.min_avg_quality),
            "min_label_classes": label_classes >= int(self._governance.min_label_classes),
        }

        reasons: List[str] = []
        if not checks["min_rows"]:
            reasons.append(
                f"dataset rows {rows} below minimum {self._governance.min_dataset_rows}"
            )
        if not checks["min_avg_quality"]:
            reasons.append(
                f"dataset avg_quality {avg_quality:.3f} below minimum {self._governance.min_avg_quality:.3f}"
            )
        if not checks["min_label_classes"]:
            reasons.append(
                f"dataset label_classes {label_classes} below minimum {self._governance.min_label_classes}"
            )

        return {
            "passed": all(checks.values()),
            "checks": checks,
            "reasons": reasons,
            "observed": {
                "rows": rows,
                "avg_quality": avg_quality,
                "label_classes": label_classes,
            },
            "thresholds": {
                "min_rows": self._governance.min_dataset_rows,
                "min_avg_quality": self._governance.min_avg_quality,
                "min_label_classes": self._governance.min_label_classes,
            },
        }

    def _recent_successful_rollbacks(self, hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        count = 0
        for run in self._read_runs(limit=500):
            if str(run.get("type", "")).lower() != "rollback":
                continue
            if str(run.get("status", "")).lower() != "success":
                continue
            ts = _parse_iso_timestamp(run.get("created_at"))
            if ts is not None and ts >= cutoff:
                count += 1
        return count

    def request_manual_retrain_approval(
        self,
        requested_by: str,
        reason: str,
        trigger: str = "manual",
        allow_cooldown_bypass: bool = False,
    ) -> Dict[str, Any]:
        approval = self._approvals.request(
            trigger=trigger,
            requested_by=requested_by,
            reason=reason,
            allow_cooldown_bypass=allow_cooldown_bypass,
            ttl_hours=self._governance.approval_ttl_hours,
        )
        self._audit_event(
            event_type="approval.requested",
            status="pending",
            trigger=trigger,
            details={
                "approval_id": approval.get("approval_id"),
                "requested_by": requested_by,
                "allow_cooldown_bypass": allow_cooldown_bypass,
            },
        )
        return approval

    def approve_manual_retrain(
        self,
        approval_id: str,
        approver_id: str,
        approver_comment: Optional[str] = None,
        allow_cooldown_bypass: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        updated = self._approvals.approve(
            approval_id=approval_id,
            approver_id=approver_id,
            approver_comment=approver_comment,
            allow_cooldown_bypass=allow_cooldown_bypass,
        )
        if updated is not None:
            self._audit_event(
                event_type="approval.approved",
                status=str(updated.get("status", "approved")),
                trigger=str(updated.get("trigger") or "manual"),
                details={
                    "approval_id": approval_id,
                    "approver_id": approver_id,
                    "allow_cooldown_bypass": updated.get("allow_cooldown_bypass", False),
                },
            )
        return updated

    def get_manual_retrain_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        return self._approvals.get(approval_id)

    def get_governance_metrics(self) -> Dict[str, float]:
        retrain_triggers = float(self._metric_state.get("retrain_triggers", 0))
        retrain_successes = float(self._metric_state.get("retrain_successes", 0))
        bypass_attempts = float(self._metric_state.get("bypass_attempts", 0))
        deploy_successes = float(self._metric_state.get("deploy_successes", 0))
        rollbacks = float(self._metric_state.get("rollbacks", 0))
        return {
            "retrain_trigger_count": retrain_triggers,
            "retrain_success_rate": retrain_successes / retrain_triggers if retrain_triggers > 0 else 0.0,
            "bypass_attempt_rate": bypass_attempts / retrain_triggers if retrain_triggers > 0 else 0.0,
            "rollback_rate": rollbacks / (deploy_successes + rollbacks) if (deploy_successes + rollbacks) > 0 else 0.0,
        }

    def get_cooldown_status(self) -> Dict[str, Any]:
        """Get current cooldown status for retraining."""
        last_retrain = self._state_store.get_last_retrain_at()
        status = self._cooldown_policy.check(last_retrain)
        return status.to_dict()

    async def train(
        self,
        trigger: str = "manual",
        source: str = "feedback",
        bypass_cooldown: bool = False,
        approval_id: Optional[str] = None,
        requested_by: str = "system",
    ) -> Dict[str, Any]:
        """Train a new model version with strict governance enforcement.
        
        Args:
            trigger: What triggered training ('manual', 'auto', 'alarm')
            source: Data source ('feedback', 'crawl')
            bypass_cooldown: Whether cooldown bypass was requested
            approval_id: Optional approval token for manual triggers and bypass requests
            requested_by: Operator/admin identifier for audit tracking
            
        Returns:
            Run result dictionary
            
        Raises:
            CooldownViolation: If auto trigger violates active cooldown
        """
        start = time.time()
        run_id = f"mlops_train_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        trigger_norm = str(trigger or "manual").strip().lower()
        manual_trigger = self._is_manual_trigger(trigger_norm)
        governed_trigger = trigger_norm in {
            "manual",
            "admin",
            "admin_ui",
            "auto",
            "scheduled",
            "drift",
            "alarm",
        }
        requested_by = str(requested_by or "unknown")
        self._record_retrain_trigger(trigger=trigger_norm, bypass_cooldown=bypass_cooldown)

        def _blocked_run(reason: str, stage: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            payload = {
                "run_id": run_id,
                "type": "train",
                "status": "blocked",
                "stage": stage,
                "trigger": trigger_norm,
                "reason": reason,
                "cooldown_status": cooldown_status.to_dict(),
                "duration_seconds": round(time.time() - start, 3),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if extra:
                payload.update(extra)
            self._append_run(payload)
            self._audit_event(
                event_type="retrain.blocked",
                status="blocked",
                run_id=run_id,
                trigger=trigger_norm,
                details={"stage": stage, "reason": reason, **(extra or {})},
            )
            return payload
        
        # Enforce cooldown policy
        last_retrain = self._state_store.get_last_retrain_at()
        cooldown_status = self._cooldown_policy.check(last_retrain, trigger_norm)
        
        logger.info(
            "Train request: trigger=%s requested_by=%s last_retrain=%s cooldown_active=%s approval=%s",
            trigger_norm,
            requested_by,
            last_retrain.isoformat() if last_retrain else "never",
            cooldown_status.active,
            approval_id,
        )

        approval_context: Optional[Dict[str, Any]] = None
        if approval_id:
            approval_ok, approval_reason, approval_record = self._approvals.consume(
                approval_id=approval_id,
                requested_by=requested_by,
                require_cooldown_bypass=(
                    bypass_cooldown and self._governance.cooldown_bypass_requires_approval
                ),
            )
            if not approval_ok:
                self._state_store.record_block("approval", approval_reason)
                return _blocked_run(
                    reason=f"Approval rejected: {approval_reason}",
                    stage="approval",
                    extra={"approval_id": approval_id},
                )
            approval_context = {
                "approval_id": approval_id,
                "approved_by": approval_record.get("approver_id") if approval_record else None,
                "allow_cooldown_bypass": bool(
                    (approval_record or {}).get("allow_cooldown_bypass", False)
                ),
            }

        if manual_trigger and self._governance.manual_approval_required and approval_context is None:
            self._state_store.record_block("approval", "manual retrain requires prior approval")
            return _blocked_run(
                reason="Manual retrain requires approved approval_id",
                stage="approval",
            )

        if bypass_cooldown and self._governance.cooldown_bypass_requires_approval and approval_context is None:
            self._state_store.record_block("approval", "cooldown bypass requires explicit approval")
            return _blocked_run(
                reason="Cooldown bypass requires explicit approval",
                stage="approval",
            )

        if cooldown_status.active and governed_trigger:
            if not bypass_cooldown:
                self._state_store.record_block(
                    "cooldown",
                    f"Remaining: {cooldown_status.remaining_hours:.2f}h",
                )
                blocked = _blocked_run(
                    reason=f"Cooldown active. {cooldown_status.remaining_hours:.2f}h remaining",
                    stage="cooldown",
                )
                if trigger_norm == "auto":
                    raise CooldownViolation(
                        message=blocked["reason"],
                        last_retrain_at=last_retrain,
                        cooldown_remaining_hours=cooldown_status.remaining_hours,
                    )
                return blocked

            if not manual_trigger:
                self._state_store.record_block("cooldown", "cooldown bypass only allowed for manual triggers")
                return _blocked_run(
                    reason="Cooldown bypass is only allowed for manual triggers",
                    stage="cooldown",
                )

            self._audit_event(
                event_type="retrain.cooldown_bypass",
                status="allowed",
                run_id=run_id,
                trigger=trigger_norm,
                details={
                    "requested_by": requested_by,
                    "approval_id": approval_context.get("approval_id") if approval_context else None,
                    "remaining_hours": cooldown_status.remaining_hours,
                },
            )

        try:
            dataset = await self._datasets.build_immutable_from_training_candidates(
                source=source,
                min_quality=self._governance.min_candidate_quality,
                skip_governance=False,
            )

            dataset_quality = self._dataset_quality_gate(dataset)
            if not bool(dataset_quality.get("passed")):
                self._state_store.record_block(
                    "quality",
                    "; ".join(dataset_quality.get("reasons", [])) or "dataset quality gate failed",
                )
                return _blocked_run(
                    reason="Dataset quality gate failed",
                    stage="dataset_quality",
                    extra={"dataset_quality": dataset_quality, "dataset": dataset.to_dict()},
                )

            rel_path = str(Path(dataset.path).resolve().relative_to(self._root)).replace("\\", "/")
            train_result = self._trainer.train_with_model(
                data_path=rel_path,
                run_id=run_id,
            )
            version = Path(train_result.model_path).name
            code_hash = self._registry.compute_code_hash()
            model_id = f"model_{version}_{train_result.dataset_hash[:8]}"
            reproducibility = {
                "docker_image": os.getenv("MLOPS_DOCKER_IMAGE", "hdss-mlops:latest"),
                "requirements": str((self._root / "requirements_data_pipeline.txt").resolve()),
                "env_vars": {
                    "PYTHONHASHSEED": os.getenv("PYTHONHASHSEED", "0"),
                    "MLOPS_DOCKER_IMAGE": os.getenv("MLOPS_DOCKER_IMAGE", "hdss-mlops:latest"),
                },
                "git_commit": self._git_commit(),
                "seed": 42,
            }
            model = RegistryModel(
                model_id=model_id,
                version=version,
                dataset_hash=dataset.hash,
                code_hash=code_hash,
                metrics=train_result.metrics,
                status="staging",
                created_at=datetime.now(timezone.utc).isoformat(),
                artifact_path=train_result.model_path,
                reproducibility=reproducibility,
                validation={"passed": False, "checks": {}},
            )
            self._registry.register(model)

            run = {
                "run_id": run_id,
                "type": "train",
                "status": "success",
                "trigger": trigger_norm,
                "requested_by": requested_by,
                "approval": approval_context,
                "cooldown_status": cooldown_status.to_dict(),
                "dataset": dataset.to_dict(),
                "dataset_quality": dataset_quality,
                "model_id": model_id,
                "version": version,
                "duration_seconds": round(time.time() - start, 3),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_run(run)
            
            # Record in state store for cooldown tracking
            self._state_store.record_retrain(
                run_id=run_id,
                trigger=trigger_norm,
                status="success",
                metrics=train_result.metrics,
            )

            self._record_retrain_success()
            self._audit_event(
                event_type="retrain.completed",
                status="success",
                run_id=run_id,
                trigger=trigger_norm,
                details={
                    "requested_by": requested_by,
                    "approval_id": approval_context.get("approval_id") if approval_context else None,
                    "model_id": model_id,
                    "dataset_id": dataset.dataset_id,
                },
            )
            
            logger.info("Training completed: %s -> %s", run_id, model_id)
            return run
        except Exception as exc:
            run = {
                "run_id": run_id,
                "type": "train",
                "status": "failed",
                "trigger": trigger_norm,
                "requested_by": requested_by,
                "approval": approval_context,
                "cooldown_status": cooldown_status.to_dict(),
                "error": str(exc),
                "duration_seconds": round(time.time() - start, 3),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_run(run)
            
            # Record failure in state store
            self._state_store.record_retrain(
                run_id=run_id,
                trigger=trigger_norm,
                status="failed",
                error=str(exc),
            )

            self._audit_event(
                event_type="retrain.completed",
                status="failed",
                run_id=run_id,
                trigger=trigger_norm,
                details={
                    "requested_by": requested_by,
                    "approval_id": approval_context.get("approval_id") if approval_context else None,
                    "error": str(exc),
                },
            )
            
            logger.error("Training failed: %s - %s", run_id, exc)
            return run

    def validate(self, model_id: Optional[str] = None, latency_sla_ms: float = 250.0, drift_threshold: float = 0.25) -> Dict[str, Any]:
        start = time.time()
        run_id = f"mlops_validate_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        target = self._registry.get(model_id) if model_id else self._registry.current_staging()
        if not target:
            result = {
                "run_id": run_id,
                "type": "validate",
                "status": "failed",
                "error": "No staging model found",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_run(result)
            return result

        metrics = target.get("metrics", {})
        val = self._validator.validate(
            version=target["version"],
            metrics=metrics,
            drift_status="LOW",
        )

        accuracy_mean = float(metrics.get("accuracy", {}).get("mean", metrics.get("accuracy", 0.0)))
        f1_mean = float(metrics.get("f1", {}).get("mean", metrics.get("f1", 0.0)))
        latency_ms = self.monitor().get("latency", 0.0)
        drift = self.monitor().get("data_drift", 0.0)

        checks = {
            "accuracy_gte_baseline": bool(accuracy_mean >= val.active_accuracy),
            "f1_gte_baseline": bool(f1_mean >= val.active_f1),
            "drift_lte_threshold": bool(drift <= drift_threshold),
            "latency_lte_sla": bool(latency_ms <= latency_sla_ms),
        }
        passed = bool(val.valid and all(checks.values()))
        validation_payload = {
            "passed": passed,
            "checks": checks,
            "blocking_reasons": ([] if passed else val.blocking_reasons + [k for k, ok in checks.items() if not ok]),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._registry.update_validation(target["model_id"], validation_payload)
        if not passed:
            self._registry.update_status(target["model_id"], "staging")

        result = {
            "run_id": run_id,
            "type": "validate",
            "status": "success" if passed else "failed",
            "model_id": target["model_id"],
            "version": target["version"],
            "validation": validation_payload,
            "duration_seconds": round(time.time() - start, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append_run(result)
        return result

    def deploy(self, model_id: str, strategy: str = "canary", canary_ratio: float = 0.1) -> Dict[str, Any]:
        run_id = f"mlops_deploy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start = time.time()
        target = self._registry.get(model_id)

        def _fail(error: str, stage: str = "deploy_gate") -> Dict[str, Any]:
            result = {
                "run_id": run_id,
                "type": "deploy",
                "status": "failed",
                "stage": stage,
                "error": error,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_run(result)
            self._audit_event(
                event_type="deploy.completed",
                status="failed",
                run_id=run_id,
                details={"model_id": model_id, "stage": stage, "error": error},
            )
            return result

        if not target:
            return _fail("Model not found")

        if target.get("status") == "prod":
            return _fail("Model already in production")

        if str(target.get("status", "")).lower() not in {"staging", "candidate"}:
            return _fail(
                f"Deployment gate failed: model status must be staging/candidate, got={target.get('status')}",
            )

        validation = target.get("validation", {})
        if not validation.get("passed", False):
            return _fail("Validation gate failed")

        metrics = target.get("metrics", {})
        accuracy_mean = _safe_float(metrics.get("accuracy", {}).get("mean", metrics.get("accuracy", 0.0)))
        f1_mean = _safe_float(metrics.get("f1", {}).get("mean", metrics.get("f1", 0.0)))
        if accuracy_mean < self._governance.deploy_min_accuracy:
            return _fail(
                f"Deployment gate failed: accuracy {accuracy_mean:.4f} < {self._governance.deploy_min_accuracy:.4f}"
            )
        if f1_mean < self._governance.deploy_min_f1:
            return _fail(
                f"Deployment gate failed: f1 {f1_mean:.4f} < {self._governance.deploy_min_f1:.4f}"
            )

        strategy = strategy.lower()
        if strategy not in {"blue-green", "canary", "shadow"}:
            return _fail("Unsupported strategy")

        if strategy == "canary" and canary_ratio > 0.1:
            return _fail("Canary ratio must be <= 0.1")

        state = self._read_deploy_state()
        state.update(
            {
                "strategy": strategy,
                "candidate_model_id": target["model_id"],
                "candidate_version": target["version"],
                "traffic_ratio": canary_ratio if strategy == "canary" else 0.0,
                "shadow_enabled": strategy == "shadow",
                "phase": "staging",
            }
        )
        self._write_deploy_state(state)
        self._registry.update_status(target["model_id"], "staging")

        result = {
            "run_id": run_id,
            "type": "deploy",
            "status": "success",
            "phase": "staging",
            "strategy": strategy,
            "model_id": target["model_id"],
            "version": target["version"],
            "canary_ratio": state["traffic_ratio"],
            "duration_seconds": round(time.time() - start, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append_run(result)
        self._record_deploy_success()
        self._audit_event(
            event_type="deploy.completed",
            status="success",
            run_id=run_id,
            details={
                "model_id": target["model_id"],
                "version": target["version"],
                "strategy": strategy,
                "canary_ratio": state["traffic_ratio"],
            },
        )
        return result

    def rollback(self, reason: str = "auto", target_model_id: Optional[str] = None) -> Dict[str, Any]:
        start = time.time()
        run_id = f"mlops_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        reason_norm = str(reason or "manual").strip().lower()

        def _fail(error: str, stage: str = "rollback_policy") -> Dict[str, Any]:
            result = {
                "run_id": run_id,
                "type": "rollback",
                "status": "failed",
                "stage": stage,
                "reason": reason_norm,
                "error": error,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_run(result)
            self._audit_event(
                event_type="rollback.completed",
                status="failed",
                run_id=run_id,
                details={
                    "reason": reason_norm,
                    "target_model_id": target_model_id,
                    "error": error,
                    "stage": stage,
                },
            )
            return result

        if reason_norm not in self._governance.rollback_allowed_reasons:
            return _fail(
                f"Rollback reason '{reason_norm}' is not in allowed reasons: {', '.join(self._governance.rollback_allowed_reasons)}"
            )

        recent_rollback_count = self._recent_successful_rollbacks(hours=24)
        if recent_rollback_count >= self._governance.rollback_max_per_24h:
            return _fail(
                f"Rollback policy limit reached: {recent_rollback_count} successful rollbacks in last 24h"
            )

        prod = self._registry.current_prod()
        candidates = [m for m in self._registry.list_models() if m.get("status") == "archived"]
        if target_model_id:
            to_restore = self._registry.get(target_model_id)
        else:
            to_restore = candidates[0] if candidates else None

        if not to_restore:
            return _fail("No rollback candidate")

        if prod and to_restore.get("model_id") == prod.get("model_id"):
            return _fail("Rollback candidate is already active production model")

        if str(to_restore.get("status", "")).lower() not in {"archived", "prod"}:
            return _fail(
                f"Rollback candidate must be archived/prod, got={to_restore.get('status')}"
            )

        validation = to_restore.get("validation", {})
        if not bool(validation.get("passed", False)):
            return _fail("Rollback candidate failed validation gate")

        self._registry.archive_prod_and_set(to_restore["model_id"], new_status="prod")
        if prod and prod.get("model_id") != to_restore.get("model_id"):
            self._registry.update_status(prod["model_id"], "archived")

        duration = round(time.time() - start, 3)
        result = {
            "run_id": run_id,
            "type": "rollback",
            "status": "success",
            "reason": reason_norm,
            "restored_model_id": to_restore["model_id"],
            "restored_version": to_restore["version"],
            "duration_seconds": duration,
            "within_30s": duration <= 30,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append_run(result)
        self._record_rollback_success()
        _metrics_inc("rollback_total", labels={"reason": reason_norm})
        self._audit_event(
            event_type="rollback.completed",
            status="success",
            run_id=run_id,
            details={
                "reason": reason_norm,
                "target_model_id": target_model_id,
                "restored_model_id": to_restore["model_id"],
                "recent_rollback_count_24h": recent_rollback_count,
            },
        )
        return result

    def monitor(self) -> Dict[str, Any]:
        metrics = {
            "accuracy_live": 0.92,
            "data_drift": 0.08,
            "concept_drift": 0.06,
            "latency": 120.0,
            "cost": 0.02,
            "error_rate": 0.01,
            "accuracy_drop": 0.01,
            "drift_score": 0.08,
            "thresholds": {
                "error_rate": 0.03,
                "accuracy_drop": 0.05,
                "drift_score": 0.25,
            },
            "alert": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        metrics["alert"] = (
            metrics["error_rate"] > metrics["thresholds"]["error_rate"]
            or metrics["accuracy_drop"] > metrics["thresholds"]["accuracy_drop"]
            or metrics["drift_score"] > metrics["thresholds"]["drift_score"]
        )
        with self._monitor_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
        return metrics

    def maybe_auto_rollback(self) -> Optional[Dict[str, Any]]:
        m = self.monitor()
        if m["alert"]:
            return self.rollback(reason="auto_guard")
        return None

    def list_models(self) -> Dict[str, Any]:
        return {"items": self._registry.list_models(), "deploy_state": self._read_deploy_state()}

    def list_runs(self, limit: int = 100) -> Dict[str, Any]:
        return {"items": self._read_runs(limit=limit)}


_manager: Optional[MLOpsManager] = None


def get_mlops_manager() -> MLOpsManager:
    global _manager
    if _manager is None:
        _manager = MLOpsManager()
    return _manager
