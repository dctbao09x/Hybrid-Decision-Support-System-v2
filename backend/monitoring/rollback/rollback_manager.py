import uuid
from dataclasses import dataclass
from typing import Dict, Any, List
import yaml

from datetime import datetime, timezone
from backend.core.telemetry.contracts import TelemetryLogEvent, ModelInfo
from backend.core.telemetry.attributes import TelemetryAttributes
from backend.core.telemetry.span_naming import SpanNames


@dataclass
class RollbackDecision:
    trigger_id: str
    action: str
    auto_action: bool
    severity: str


def _load_policy(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def evaluate_rollback(policy_path: str, metrics: Dict[str, float]) -> List[RollbackDecision]:
    policy = _load_policy(policy_path)
    decisions: List[RollbackDecision] = []
    for trigger in policy.get("rollback_triggers", []):
        trigger_id = trigger.get("id")
        condition = trigger.get("trigger", "")
        if _evaluate_condition(condition, metrics):
            decisions.append(
                RollbackDecision(
                    trigger_id=trigger_id,
                    action=trigger.get("action", ""),
                    auto_action=bool(trigger.get("auto_action")),
                    severity=trigger.get("severity", "P2"),
                )
            )
    return decisions


def _evaluate_condition(condition: str, metrics: Dict[str, float]) -> bool:
    # Minimal evaluator: support "metric > value" style.
    parts = condition.split()
    if len(parts) < 3:
        return False
    metric, op, value = parts[0], parts[1], parts[2]
    try:
        threshold = float(value)
    except ValueError:
        return False
    current = metrics.get(metric)
    if current is None:
        return False
    if op == ">":
        return current > threshold
    if op == "<":
        return current < threshold
    return False


def build_audit_event(
    *,
    trigger_id: str,
    action: str,
    model_id: str,
    model_version: str,
    previous_model_version: str,
    metrics_snapshot: Dict[str, float],
) -> TelemetryLogEvent:
    rollback_id = str(uuid.uuid4())
    return TelemetryLogEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=SpanNames.ROLLBACK_EXECUTE,
        severity="ERROR",
        component="rollback",
        status="triggered",
        rollback_id=rollback_id,
        rollback_action=action,
        rollback_trigger=trigger_id,
        model=ModelInfo(model_id=model_id, model_version=model_version),
        payload_snippet=str(metrics_snapshot)[:512],
    )
