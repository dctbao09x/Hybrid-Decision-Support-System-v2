"""
Quality Gate — blocks bad data before scoring.
================================================

Orchestrates all quality checks (schema, missing, outlier, drift)
into a single pass/fail verdict with audit trail.

Usage::

    from backend.ops.quality.quality_gate import QualityGate, GateVerdict

    gate = QualityGate()                         # loads config/quality_gate.yaml
    verdict = gate.evaluate(records, run_id=run_id)

    if verdict.blocked:
        raise PipelineError("validate", verdict.summary, run_id)

Every check produces a ``CheckResult``; the gate aggregates them into
a ``GateVerdict`` with ``blocked: bool``, ``checks: list``, ``summary: str``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("ops.quality_gate")

# ═══════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    """Outcome of a single quality check."""

    name: str                         # e.g. "schema", "missing", "outlier", "drift"
    passed: bool                      # True = OK
    mode: str = "strict"              # "strict" | "warn"
    blocked: bool = False             # True only if mode=strict AND passed=False
    severity: str = "info"            # "info" | "warning" | "critical"
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "mode": self.mode,
            "blocked": self.blocked,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class GateVerdict:
    """Aggregated outcome of all quality checks."""

    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    blocked: bool = False             # True if ANY strict check failed
    checks: List[CheckResult] = field(default_factory=list)
    total_records: int = 0
    valid_records: int = 0
    duration_ms: float = 0.0

    @property
    def summary(self) -> str:
        failed = [c for c in self.checks if c.blocked]
        warned = [c for c in self.checks if not c.passed and not c.blocked]
        if failed:
            names = ", ".join(c.name for c in failed)
            return (
                f"BLOCKED by {len(failed)} gate(s): {names}. "
                f"{len(warned)} warning(s)."
            )
        if warned:
            names = ", ".join(c.name for c in warned)
            return f"PASSED with {len(warned)} warning(s): {names}."
        return "PASSED — all checks clean."

    @property
    def passed_checks(self) -> List[CheckResult]:
        return [c for c in self.checks if c.passed]

    @property
    def failed_checks(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def blocking_checks(self) -> List[CheckResult]:
        return [c for c in self.checks if c.blocked]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "blocked": self.blocked,
            "summary": self.summary,
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "duration_ms": round(self.duration_ms, 2),
            "checks": [c.to_dict() for c in self.checks],
        }


# ═══════════════════════════════════════════════════════════════════════════
#  QualityGate
# ═══════════════════════════════════════════════════════════════════════════


class QualityGate:
    """
    Centralized quality gate that orchestrates all checks.

    Loads thresholds from ``config/quality_gate.yaml``.
    Each check method returns ``CheckResult``; ``evaluate()`` collects them
    into a single ``GateVerdict``.
    """

    DEFAULT_CONFIG_PATH = Path("config/quality_gate.yaml")

    def __init__(
        self,
        config_path: Optional[Path] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._cfg = self._load_config(config_path or self.DEFAULT_CONFIG_PATH)
        if config_override:
            self._deep_merge(self._cfg, config_override)
        self._gate_cfg = self._cfg.get("quality_gate", {})

    # ── Public API ────────────────────────────────────────────────

    def evaluate(
        self,
        records: List[Dict[str, Any]],
        run_id: str = "",
        baseline_name: Optional[str] = None,
        raw_count: Optional[int] = None,
        validation_report: Optional[Any] = None,
    ) -> GateVerdict:
        """
        Run ALL quality checks on ``records`` and return a verdict.

        Args:
            records:           Processed/clean records (list of dicts).
            run_id:            Pipeline run id for traceability.
            baseline_name:     Name of the drift baseline batch to compare against.
            raw_count:         Total raw records before validation (for rate calc).
            validation_report: Optional ValidationReport from DataValidator.

        Returns:
            GateVerdict with ``blocked=True`` if any strict check fails.
        """
        if not self._gate_cfg.get("enabled", True):
            logger.warning("Quality gate DISABLED by config")
            return GateVerdict(
                run_id=run_id,
                total_records=len(records),
                valid_records=len(records),
            )

        gate_t0 = time.monotonic()
        fail_fast = self._gate_cfg.get("fail_fast", True)
        verdict = GateVerdict(
            run_id=run_id,
            total_records=raw_count or len(records),
            valid_records=len(records),
        )

        # Ordered checks — each can block
        check_fns = [
            self._check_schema,
            self._check_missing,
            self._check_validation_rate,
            self._check_duplicates,
            self._check_outlier,
            self._check_drift,
        ]

        for check_fn in check_fns:
            try:
                result = check_fn(
                    records,
                    run_id=run_id,
                    baseline_name=baseline_name,
                    raw_count=raw_count,
                    validation_report=validation_report,
                )
                verdict.checks.append(result)

                if result.blocked:
                    verdict.blocked = True
                    if fail_fast:
                        logger.error(
                            f"[{run_id}] Quality gate BLOCKED (fail-fast) "
                            f"by '{result.name}': {result.message}"
                        )
                        break
            except Exception as e:
                logger.error(
                    f"[{run_id}] Quality check error in "
                    f"'{check_fn.__name__}': {e}"
                )
                verdict.checks.append(
                    CheckResult(
                        name=check_fn.__name__.replace("_check_", ""),
                        passed=False,
                        mode="strict",
                        blocked=True,
                        severity="critical",
                        message=f"Check raised exception: {e}",
                    )
                )
                verdict.blocked = True
                if fail_fast:
                    break

        verdict.duration_ms = (time.monotonic() - gate_t0) * 1000

        level = logging.ERROR if verdict.blocked else logging.INFO
        logger.log(
            level,
            f"[{run_id}] Quality gate verdict: {verdict.summary} "
            f"({verdict.duration_ms:.1f}ms)",
        )

        return verdict

    # ── Individual checks ─────────────────────────────────────────

    def _check_schema(self, records, **ctx) -> CheckResult:
        """Validate every record against its Pydantic schema."""
        cfg = self._gate_cfg.get("schema", {})
        if not cfg.get("enabled", True):
            return CheckResult(name="schema", passed=True, message="disabled")

        t0 = time.monotonic()
        mode = cfg.get("mode", "strict")
        max_invalid_rate = cfg.get("max_invalid_rate", 0.0)

        # Dynamically import the target schema
        schema_class = self._resolve_schema(
            cfg.get("stages", {}).get("validate_output")
        )

        valid = 0
        invalid = 0
        errors: List[Dict[str, Any]] = []

        for i, rec in enumerate(records):
            if schema_class:
                try:
                    schema_class(**rec)
                    valid += 1
                except Exception as e:
                    invalid += 1
                    if len(errors) < 50:
                        errors.append({
                            "index": i,
                            "error": str(e)[:200],
                            "record_id": rec.get("id", rec.get("job_id", "?")),
                        })
            else:
                # No schema registered — treat as warning
                valid += 1

        total = valid + invalid
        invalid_rate = invalid / total if total else 0.0
        passed = invalid_rate <= max_invalid_rate
        blocked = not passed and mode == "strict"

        return CheckResult(
            name="schema",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity="critical" if blocked else ("warning" if not passed else "info"),
            message=(
                f"Schema: {invalid}/{total} invalid "
                f"({invalid_rate:.1%} vs max {max_invalid_rate:.1%})"
            ),
            details={
                "valid": valid,
                "invalid": invalid,
                "invalid_rate": round(invalid_rate, 4),
                "max_invalid_rate": max_invalid_rate,
                "errors": errors[:20],
            },
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def _check_missing(self, records, **ctx) -> CheckResult:
        """Check field completeness — <5% missing required."""
        cfg = self._gate_cfg.get("missing", {})
        if not cfg.get("enabled", True):
            return CheckResult(name="missing", passed=True, message="disabled")

        t0 = time.monotonic()
        mode = cfg.get("mode", "strict")
        min_completeness = cfg.get("min_completeness", 0.95)
        critical_fields = cfg.get("critical_fields", [])
        important_fields = cfg.get("important_fields", [])
        important_min = cfg.get("important_min_completeness", 0.80)

        if not records:
            return CheckResult(
                name="missing", passed=True, mode=mode,
                message="No records to check",
            )

        total = len(records)
        field_stats: Dict[str, Dict[str, Any]] = {}
        critical_failures: List[Dict[str, Any]] = []

        # Check critical fields
        for fld in critical_fields:
            filled = sum(
                1 for r in records
                if r.get(fld) is not None and str(r.get(fld, "")).strip()
            )
            rate = filled / total
            field_stats[fld] = {
                "filled": filled,
                "total": total,
                "rate": round(rate, 4),
                "category": "critical",
            }
            if rate < 1.0:
                missing_indices = [
                    i for i, r in enumerate(records)
                    if r.get(fld) is None or not str(r.get(fld, "")).strip()
                ]
                critical_failures.append({
                    "field": fld,
                    "missing_count": total - filled,
                    "rate": round(rate, 4),
                    "sample_indices": missing_indices[:5],
                })

        # Check important fields
        important_warnings: List[Dict[str, Any]] = []
        for fld in important_fields:
            filled = sum(
                1 for r in records
                if r.get(fld) is not None and str(r.get(fld, "")).strip()
            )
            rate = filled / total
            field_stats[fld] = {
                "filled": filled,
                "total": total,
                "rate": round(rate, 4),
                "category": "important",
            }
            if rate < important_min:
                important_warnings.append({
                    "field": fld,
                    "rate": round(rate, 4),
                    "threshold": important_min,
                })

        # Overall completeness (all fields)
        all_fields = set()
        for r in records:
            all_fields.update(r.keys())

        total_cells = len(all_fields) * total
        filled_cells = sum(
            1 for r in records for fld in all_fields
            if r.get(fld) is not None and str(r.get(fld, "")).strip()
        )
        overall = filled_cells / total_cells if total_cells else 1.0

        # Verdict
        passed = (
            len(critical_failures) == 0
            and overall >= min_completeness
        )
        blocked = not passed and mode == "strict"

        msg_parts = []
        if critical_failures:
            msg_parts.append(
                f"{len(critical_failures)} critical field(s) have gaps"
            )
        if overall < min_completeness:
            msg_parts.append(
                f"overall completeness {overall:.1%} < {min_completeness:.1%}"
            )
        if important_warnings:
            msg_parts.append(
                f"{len(important_warnings)} important field(s) below threshold"
            )

        return CheckResult(
            name="missing",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity="critical" if blocked else (
                "warning" if not passed or important_warnings else "info"
            ),
            message=(
                "Missing: " + "; ".join(msg_parts) if msg_parts
                else f"Missing: completeness {overall:.1%} OK"
            ),
            details={
                "overall_completeness": round(overall, 4),
                "min_completeness": min_completeness,
                "critical_failures": critical_failures,
                "important_warnings": important_warnings,
                "field_stats": field_stats,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def _check_validation_rate(self, records, **ctx) -> CheckResult:
        """Check ratio of valid records to raw records."""
        cfg = self._gate_cfg.get("validation_rate", {})
        if not cfg.get("enabled", True):
            return CheckResult(
                name="validation_rate", passed=True, message="disabled"
            )

        t0 = time.monotonic()
        mode = cfg.get("mode", "strict")
        min_rate = cfg.get("min_rate", 0.50)
        warning_rate = cfg.get("warning_rate", 0.80)

        raw_count = ctx.get("raw_count") or len(records)
        valid_count = len(records)
        rate = valid_count / raw_count if raw_count else 1.0

        passed = rate >= min_rate
        blocked = not passed and mode == "strict"
        is_warning = passed and rate < warning_rate

        return CheckResult(
            name="validation_rate",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity=(
                "critical" if blocked
                else "warning" if is_warning
                else "info"
            ),
            message=(
                f"Validation rate: {rate:.1%} "
                f"({valid_count}/{raw_count}) "
                f"{'< min ' + str(min_rate) if not passed else 'OK'}"
            ),
            details={
                "rate": round(rate, 4),
                "raw_count": raw_count,
                "valid_count": valid_count,
                "min_rate": min_rate,
                "warning_rate": warning_rate,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def _check_duplicates(self, records, **ctx) -> CheckResult:
        """Check for duplicate records."""
        cfg = self._gate_cfg.get("duplicates", {})
        if not cfg.get("enabled", True):
            return CheckResult(
                name="duplicates", passed=True, message="disabled"
            )

        t0 = time.monotonic()
        mode = cfg.get("mode", "warn")
        max_rate = cfg.get("max_duplicate_rate", 0.05)

        seen: set = set()
        dup_count = 0
        for r in records:
            key = (
                r.get("id")
                or r.get("job_id", "")
                + "_"
                + r.get("url", "")
            )
            if key in seen:
                dup_count += 1
            else:
                seen.add(key)

        total = len(records)
        dup_rate = dup_count / total if total else 0.0
        passed = dup_rate <= max_rate
        blocked = not passed and mode == "strict"

        return CheckResult(
            name="duplicates",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity="warning" if not passed else "info",
            message=(
                f"Duplicates: {dup_count}/{total} ({dup_rate:.1%}) "
                f"{'> max ' + str(max_rate) if not passed else 'OK'}"
            ),
            details={
                "duplicate_count": dup_count,
                "total": total,
                "duplicate_rate": round(dup_rate, 4),
                "max_rate": max_rate,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def _check_outlier(self, records, **ctx) -> CheckResult:
        """Detect outliers via IQR and/or z-score."""
        cfg = self._gate_cfg.get("outlier", {})
        if not cfg.get("enabled", True):
            return CheckResult(
                name="outlier", passed=True, message="disabled"
            )

        t0 = time.monotonic()
        mode = cfg.get("mode", "warn")
        method = cfg.get("method", "both")
        iqr_mult = cfg.get("iqr_multiplier", 1.5)
        z_thresh = cfg.get("z_threshold", 3.0)
        max_rate = cfg.get("max_outlier_rate", 0.10)
        fields_to_check = cfg.get("numeric_fields", [])

        if not records or not fields_to_check:
            return CheckResult(
                name="outlier", passed=True, mode=mode,
                message="No numeric fields to check",
            )

        field_reports: Dict[str, Dict[str, Any]] = {}
        worst_rate = 0.0

        for fld in fields_to_check:
            values = []
            for r in records:
                v = r.get(fld)
                if v is not None:
                    try:
                        values.append(float(v))
                    except (ValueError, TypeError):
                        pass

            if len(values) < 5:
                field_reports[fld] = {"skipped": True, "reason": "too few values"}
                continue

            outlier_indices_iqr: set = set()
            outlier_indices_z: set = set()
            bounds: Dict[str, Any] = {}

            if method in ("iqr", "both"):
                iqr_result = self._detect_iqr(values, iqr_mult)
                outlier_indices_iqr = iqr_result["outlier_indices"]
                bounds["iqr"] = iqr_result["bounds"]

            if method in ("zscore", "both"):
                z_result = self._detect_zscore(values, z_thresh)
                outlier_indices_z = z_result["outlier_indices"]
                bounds["zscore"] = z_result["bounds"]

            # Union of detected outliers
            all_outliers = outlier_indices_iqr | outlier_indices_z
            rate = len(all_outliers) / len(values) if values else 0.0
            worst_rate = max(worst_rate, rate)

            field_reports[fld] = {
                "total_values": len(values),
                "outlier_count": len(all_outliers),
                "outlier_rate": round(rate, 4),
                "bounds": bounds,
                "method": method,
            }

        passed = worst_rate <= max_rate
        blocked = not passed and mode == "strict"

        # Score anomaly sub-check
        score_cfg = cfg.get("score_check", {})
        score_report: Dict[str, Any] = {}
        if score_cfg.get("enabled", False) and records:
            score_report = self._check_score_anomalies(
                records, score_cfg.get("max_anomaly_rate", 0.05)
            )
            if score_report.get("anomaly_rate", 0) > score_cfg.get("max_anomaly_rate", 0.05):
                if mode == "strict":
                    passed = False
                    blocked = True

        return CheckResult(
            name="outlier",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity="critical" if blocked else (
                "warning" if not passed else "info"
            ),
            message=(
                f"Outlier: worst field rate {worst_rate:.1%} "
                f"{'> max ' + str(max_rate) if not passed else 'OK'}"
            ),
            details={
                "fields": field_reports,
                "max_outlier_rate": max_rate,
                "worst_rate": round(worst_rate, 4),
                "score_anomalies": score_report,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def _check_drift(self, records, **ctx) -> CheckResult:
        """Detect distribution drift via PSI and JSD."""
        cfg = self._gate_cfg.get("drift", {})
        if not cfg.get("enabled", True):
            return CheckResult(
                name="drift", passed=True, message="disabled"
            )

        t0 = time.monotonic()
        mode = cfg.get("mode", "strict")
        baseline_name = ctx.get("baseline_name")
        run_id = ctx.get("run_id", "")

        # Load baseline
        baseline_profile = self._load_baseline(baseline_name)
        if not baseline_profile:
            logger.info(
                f"[{run_id}] No drift baseline found — "
                f"setting current batch as initial baseline"
            )
            self._save_baseline(run_id, records)
            return CheckResult(
                name="drift", passed=True, mode=mode,
                message="No baseline — first run, setting baseline",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # Build current profile
        current_profile = self._profile_batch(records, cfg)

        # Compare
        drift_details = self._compute_drift(
            baseline_profile, current_profile, cfg
        )

        # Determine verdict
        max_psi = drift_details.get("max_psi", 0.0)
        max_jsd = drift_details.get("max_jsd", 0.0)
        volume_blocked = drift_details.get("volume_blocked", False)
        schema_blocked = drift_details.get("schema_blocked", False)

        psi_cfg = cfg.get("psi", {})
        jsd_cfg = cfg.get("jsd", {})

        psi_block = (
            psi_cfg.get("enabled", True)
            and max_psi > psi_cfg.get("threshold", 0.20)
        )
        jsd_block = (
            jsd_cfg.get("enabled", True)
            and max_jsd > jsd_cfg.get("threshold", 0.15)
        )

        psi_warn = (
            psi_cfg.get("enabled", True)
            and max_psi > psi_cfg.get("warning_threshold", 0.10)
            and not psi_block
        )
        jsd_warn = (
            jsd_cfg.get("enabled", True)
            and max_jsd > jsd_cfg.get("warning_threshold", 0.08)
            and not jsd_block
        )

        any_block = psi_block or jsd_block or volume_blocked or schema_blocked
        passed = not any_block
        blocked = not passed and mode == "strict"

        # Build message
        msg_parts = []
        if psi_block:
            msg_parts.append(f"PSI={max_psi:.3f} > {psi_cfg.get('threshold', 0.20)}")
        if jsd_block:
            msg_parts.append(f"JSD={max_jsd:.3f} > {jsd_cfg.get('threshold', 0.15)}")
        if volume_blocked:
            msg_parts.append("volume swing critical")
        if schema_blocked:
            msg_parts.append("schema fields changed")
        if psi_warn:
            msg_parts.append(f"PSI={max_psi:.3f} warning")
        if jsd_warn:
            msg_parts.append(f"JSD={max_jsd:.3f} warning")

        # Save current as new baseline (for next run)
        self._save_baseline(run_id, records)

        return CheckResult(
            name="drift",
            passed=passed,
            mode=mode,
            blocked=blocked,
            severity=(
                "critical" if blocked
                else "warning" if psi_warn or jsd_warn
                else "info"
            ),
            message=(
                "Drift: " + "; ".join(msg_parts)
                if msg_parts
                else "Drift: no significant drift detected"
            ),
            details=drift_details,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # ── Outlier helpers ───────────────────────────────────────────

    @staticmethod
    def _detect_iqr(
        values: List[float], multiplier: float = 1.5
    ) -> Dict[str, Any]:
        sorted_v = sorted(values)
        n = len(sorted_v)
        q1 = sorted_v[n // 4]
        q3 = sorted_v[3 * n // 4]
        iqr = q3 - q1
        lower = q1 - multiplier * iqr
        upper = q3 + multiplier * iqr
        outlier_indices = {
            i for i, v in enumerate(values) if v < lower or v > upper
        }
        return {
            "outlier_indices": outlier_indices,
            "bounds": {
                "q1": q1, "q3": q3, "iqr": iqr,
                "lower": lower, "upper": upper,
            },
        }

    @staticmethod
    def _detect_zscore(
        values: List[float], threshold: float = 3.0
    ) -> Dict[str, Any]:
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance) if variance > 0 else 1e-10
        outlier_indices = {
            i for i, v in enumerate(values) if abs((v - mean) / std) > threshold
        }
        return {
            "outlier_indices": outlier_indices,
            "bounds": {
                "mean": round(mean, 2),
                "std": round(std, 2),
                "threshold": threshold,
            },
        }

    @staticmethod
    def _check_score_anomalies(
        records: List[Dict[str, Any]], max_rate: float
    ) -> Dict[str, Any]:
        """Check for score values outside [0, 1] or uniform components."""
        anomalies: List[Dict[str, Any]] = []
        for i, r in enumerate(records):
            ts = r.get("total_score")
            if ts is not None:
                try:
                    score = float(ts)
                    if score < 0 or score > 1:
                        anomalies.append({
                            "index": i,
                            "type": "out_of_bounds",
                            "score": score,
                        })
                except (ValueError, TypeError):
                    pass

        total = sum(
            1 for r in records if r.get("total_score") is not None
        )
        rate = len(anomalies) / total if total else 0.0
        return {
            "total_scored": total,
            "anomaly_count": len(anomalies),
            "anomaly_rate": round(rate, 4),
            "max_rate": max_rate,
            "anomalies": anomalies[:20],
        }

    # ── Drift helpers ─────────────────────────────────────────────

    def _profile_batch(
        self, records: List[Dict[str, Any]], cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a statistical profile of the current batch."""
        numeric_fields = cfg.get("numeric_fields", ["salary_min", "salary_max"])
        categorical_fields = cfg.get(
            "categorical_fields",
            ["location", "province_code", "job_type", "source"],
        )

        profile: Dict[str, Any] = {
            "record_count": len(records),
            "fields": list(set().union(*(r.keys() for r in records)) if records else []),
            "numeric": {},
            "categorical": {},
        }

        # Numeric profiles
        for fld in numeric_fields:
            values = []
            for r in records:
                v = r.get(fld)
                if v is not None:
                    try:
                        values.append(float(v))
                    except (ValueError, TypeError):
                        pass
            if values:
                histogram = self._make_histogram(values, bins=10)
                profile["numeric"][fld] = {
                    "count": len(values),
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "histogram": histogram,
                }

        # Categorical profiles
        for fld in categorical_fields:
            counts: Dict[str, int] = {}
            total = 0
            for r in records:
                v = r.get(fld)
                if v is not None:
                    key = str(v).strip()
                    if key:
                        counts[key] = counts.get(key, 0) + 1
                        total += 1
            if total > 0:
                dist = {k: v / total for k, v in counts.items()}
                profile["categorical"][fld] = {
                    "count": total,
                    "unique": len(counts),
                    "distribution": dist,
                }

        return profile

    def _compute_drift(
        self,
        baseline: Dict[str, Any],
        current: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compare baseline vs current profile. Returns drift metrics."""
        result: Dict[str, Any] = {
            "feature_drifts": {},
            "max_psi": 0.0,
            "max_jsd": 0.0,
            "volume_drift": {},
            "schema_drift": {},
            "volume_blocked": False,
            "schema_blocked": False,
        }

        # Volume drift
        vol_cfg = cfg.get("volume", {})
        if vol_cfg.get("enabled", True):
            base_count = baseline.get("record_count", 0)
            cur_count = current.get("record_count", 0)
            if base_count > 0:
                change = abs(cur_count - base_count) / base_count
            else:
                change = 1.0 if cur_count > 0 else 0.0
            result["volume_drift"] = {
                "baseline_count": base_count,
                "current_count": cur_count,
                "change_rate": round(change, 4),
            }
            critical_rate = vol_cfg.get("critical_change_rate", 0.50)
            if change > critical_rate:
                result["volume_blocked"] = True

        # Schema drift
        schema_cfg = cfg.get("schema_drift", {})
        if schema_cfg.get("enabled", True):
            base_fields = set(baseline.get("fields", []))
            cur_fields = set(current.get("fields", []))
            added = cur_fields - base_fields
            removed = base_fields - cur_fields
            if added or removed:
                result["schema_drift"] = {
                    "added_fields": sorted(added),
                    "removed_fields": sorted(removed),
                }
                if schema_cfg.get("mode", "strict") == "strict" and removed:
                    result["schema_blocked"] = True

        # Numeric field drift (PSI + JSD)
        for fld in cfg.get("numeric_fields", []):
            base_num = baseline.get("numeric", {}).get(fld)
            cur_num = current.get("numeric", {}).get(fld)
            if not base_num or not cur_num:
                continue

            base_hist = base_num.get("histogram", [])
            cur_hist = cur_num.get("histogram", [])
            if base_hist and cur_hist and len(base_hist) == len(cur_hist):
                psi = self._compute_psi(base_hist, cur_hist)
                jsd = self._compute_jsd(base_hist, cur_hist)
                result["feature_drifts"][fld] = {
                    "type": "numeric",
                    "psi": round(psi, 4),
                    "jsd": round(jsd, 4),
                    "base_mean": round(base_num.get("mean", 0), 2),
                    "cur_mean": round(cur_num.get("mean", 0), 2),
                }
                result["max_psi"] = max(result["max_psi"], psi)
                result["max_jsd"] = max(result["max_jsd"], jsd)

        # Categorical field drift (PSI + JSD)
        for fld in cfg.get("categorical_fields", []):
            base_cat = baseline.get("categorical", {}).get(fld)
            cur_cat = current.get("categorical", {}).get(fld)
            if not base_cat or not cur_cat:
                continue

            base_dist = base_cat.get("distribution", {})
            cur_dist = cur_cat.get("distribution", {})

            psi = self._compute_categorical_psi(base_dist, cur_dist)
            jsd = self._compute_categorical_jsd(base_dist, cur_dist)
            result["feature_drifts"][fld] = {
                "type": "categorical",
                "psi": round(psi, 4),
                "jsd": round(jsd, 4),
                "base_unique": base_cat.get("unique", 0),
                "cur_unique": cur_cat.get("unique", 0),
            }
            result["max_psi"] = max(result["max_psi"], psi)
            result["max_jsd"] = max(result["max_jsd"], jsd)

        return result

    # ── PSI / JSD computation ─────────────────────────────────────

    @staticmethod
    def _make_histogram(
        values: List[float], bins: int = 10
    ) -> List[float]:
        """Create a normalized histogram (fractions sum to 1)."""
        if not values:
            return [0.0] * bins
        mn, mx = min(values), max(values)
        if mn == mx:
            result = [0.0] * bins
            result[0] = 1.0
            return result
        bin_width = (mx - mn) / bins
        counts = [0] * bins
        for v in values:
            idx = min(int((v - mn) / bin_width), bins - 1)
            counts[idx] += 1
        total = sum(counts)
        return [c / total for c in counts] if total else [0.0] * bins

    @staticmethod
    def _compute_psi(
        ref_hist: List[float], cur_hist: List[float]
    ) -> float:
        """Population Stability Index between two histograms."""
        eps = 1e-6
        psi = 0.0
        for p, q in zip(ref_hist, cur_hist):
            p = max(p, eps)
            q = max(q, eps)
            psi += (q - p) * math.log(q / p)
        return psi

    @staticmethod
    def _compute_jsd(
        ref_hist: List[float], cur_hist: List[float]
    ) -> float:
        """Jensen-Shannon Divergence between two histograms."""
        eps = 1e-10

        def kl(p_dist: List[float], q_dist: List[float]) -> float:
            return sum(
                pi * math.log((pi + eps) / (qi + eps))
                for pi, qi in zip(p_dist, q_dist)
                if pi > eps
            )

        m = [(p + q) / 2 for p, q in zip(ref_hist, cur_hist)]
        return 0.5 * kl(ref_hist, m) + 0.5 * kl(cur_hist, m)

    @staticmethod
    def _compute_categorical_psi(
        ref_dist: Dict[str, float], cur_dist: Dict[str, float]
    ) -> float:
        """PSI for categorical distributions."""
        eps = 1e-6
        all_keys = set(ref_dist) | set(cur_dist)
        psi = 0.0
        for k in all_keys:
            p = max(ref_dist.get(k, 0.0), eps)
            q = max(cur_dist.get(k, 0.0), eps)
            psi += (q - p) * math.log(q / p)
        return psi

    @staticmethod
    def _compute_categorical_jsd(
        ref_dist: Dict[str, float], cur_dist: Dict[str, float]
    ) -> float:
        """JSD for categorical distributions."""
        eps = 1e-10
        all_keys = sorted(set(ref_dist) | set(cur_dist))
        p_vec = [max(ref_dist.get(k, 0.0), eps) for k in all_keys]
        q_vec = [max(cur_dist.get(k, 0.0), eps) for k in all_keys]
        m_vec = [(a + b) / 2 for a, b in zip(p_vec, q_vec)]

        def kl(a: List[float], b: List[float]) -> float:
            return sum(
                ai * math.log(ai / bi)
                for ai, bi in zip(a, b)
                if ai > eps
            )

        return 0.5 * kl(p_vec, m_vec) + 0.5 * kl(q_vec, m_vec)

    # ── Baseline persistence ──────────────────────────────────────

    _BASELINE_DIR = Path("backend/data/quality_baselines")

    def _load_baseline(
        self, name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load the latest (or named) baseline profile from disk."""
        import json

        base_dir = self._BASELINE_DIR
        if not base_dir.exists():
            return None

        if name:
            path = base_dir / f"{name}.json"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)

        # Fall back to latest
        files = sorted(base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        with open(files[-1], "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_baseline(
        self, name: str, records: List[Dict[str, Any]]
    ) -> None:
        """Save a baseline profile for future drift comparison."""
        import json

        cfg = self._gate_cfg.get("drift", {})
        profile = self._profile_batch(records, cfg)
        profile["baseline_name"] = name
        profile["saved_at"] = datetime.now().isoformat()

        base_dir = self._BASELINE_DIR
        base_dir.mkdir(parents=True, exist_ok=True)

        path = base_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, default=str)

        logger.debug(f"Saved drift baseline: {path}")

    # ── Config loading ────────────────────────────────────────────

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        logger.warning(
            f"Quality gate config not found at {path}, using defaults"
        )
        return {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                QualityGate._deep_merge(base[k], v)
            else:
                base[k] = v

    @staticmethod
    def _resolve_schema(dotted_path: Optional[str]):
        """Import a Pydantic model from a dotted path like 'pkg.mod.Class'."""
        if not dotted_path:
            return None
        try:
            parts = dotted_path.rsplit(".", 1)
            if len(parts) != 2:
                return None
            mod_path, cls_name = parts
            import importlib
            mod = importlib.import_module(mod_path)
            return getattr(mod, cls_name, None)
        except Exception as e:
            logger.warning(f"Cannot resolve schema '{dotted_path}': {e}")
            return None
