from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

_STATE_LOCK = threading.Lock()
_METRICS_COLLECTOR: Optional[Any] = None
_STATE: Dict[str, int] = {
    "contract_total": 0,
    "contract_passed": 0,
    "startup_parity_total": 0,
    "startup_parity_passed": 0,
    "schema_regression_total": 0,
    "schema_regression_failures": 0,
}


def set_metrics_collector(metrics_collector: Any) -> None:
    global _METRICS_COLLECTOR
    _METRICS_COLLECTOR = metrics_collector


def _set_gauge(name: str, value: float) -> None:
    if _METRICS_COLLECTOR is None:
        return
    try:
        _METRICS_COLLECTOR.set_gauge(name, float(value))
    except Exception:
        pass


def _compute_rates_locked() -> Dict[str, float]:
    contract_total = max(_STATE["contract_total"], 1)
    startup_total = max(_STATE["startup_parity_total"], 1)
    schema_total = max(_STATE["schema_regression_total"], 1)

    return {
        "contract_test_pass_rate": _STATE["contract_passed"] / contract_total,
        "startup_parity_pass_rate": _STATE["startup_parity_passed"] / startup_total,
        "schema_regression_rate": _STATE["schema_regression_failures"] / schema_total,
    }


def record_test_result(
    *,
    passed: bool,
    startup_parity: bool = False,
    schema_regression: bool = False,
) -> None:
    with _STATE_LOCK:
        _STATE["contract_total"] += 1
        if passed:
            _STATE["contract_passed"] += 1

        if startup_parity:
            _STATE["startup_parity_total"] += 1
            if passed:
                _STATE["startup_parity_passed"] += 1

        if schema_regression:
            _STATE["schema_regression_total"] += 1
            if not passed:
                _STATE["schema_regression_failures"] += 1

        rates = _compute_rates_locked()

    _set_gauge("contract_test_pass_rate", rates["contract_test_pass_rate"])
    _set_gauge("startup_parity_pass_rate", rates["startup_parity_pass_rate"])
    _set_gauge("schema_regression_rate", rates["schema_regression_rate"])


def get_metric_snapshot() -> Dict[str, Any]:
    with _STATE_LOCK:
        rates = _compute_rates_locked()
        snapshot: Dict[str, Any] = {
            "counts": dict(_STATE),
            "metrics": rates,
        }
    return snapshot


def write_metric_artifact(output_path: Optional[Path] = None) -> Path:
    root = Path(__file__).resolve().parents[2]
    artifact_path = output_path or (root / "audit_outputs" / "contract_test_metrics.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = get_metric_snapshot()

    # Avoid overwriting the last contract run artifact when a test session has
    # no contract-marked tests.
    if payload["counts"].get("contract_total", 0) == 0 and artifact_path.exists():
        return artifact_path

    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact_path
