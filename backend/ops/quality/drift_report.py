"""
Drift Report — structured report for drift detection results.
==============================================================

Produces a human-readable + machine-parseable report from a
QualityGate drift check.  Used for:

  • Audit trail entries
  • Slack/webhook alert payloads
  • On-disk report persistence (JSON + text)
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class DriftReport:
    """
    Structured drift report generated from QualityGate ``_check_drift``.

    Usage::

        from backend.ops.quality.drift_report import DriftReport

        report = DriftReport.from_check_result(check_result, run_id="run_abc123")
        print(report.to_text())
        report.save("backend/data/quality_reports")
    """

    def __init__(
        self,
        run_id: str = "",
        timestamp: str = "",
        blocked: bool = False,
        severity: str = "info",
        message: str = "",
        max_psi: float = 0.0,
        max_jsd: float = 0.0,
        feature_drifts: Optional[Dict[str, Dict[str, Any]]] = None,
        volume_drift: Optional[Dict[str, Any]] = None,
        schema_drift: Optional[Dict[str, Any]] = None,
        psi_threshold: float = 0.20,
        jsd_threshold: float = 0.15,
        baseline_name: str = "",
    ) -> None:
        self.run_id = run_id
        self.timestamp = timestamp or datetime.now().isoformat()
        self.blocked = blocked
        self.severity = severity
        self.message = message
        self.max_psi = max_psi
        self.max_jsd = max_jsd
        self.feature_drifts = feature_drifts or {}
        self.volume_drift = volume_drift or {}
        self.schema_drift = schema_drift or {}
        self.psi_threshold = psi_threshold
        self.jsd_threshold = jsd_threshold
        self.baseline_name = baseline_name

    # ── Factory ───────────────────────────────────────────────────

    @classmethod
    def from_check_result(
        cls,
        check_result,       # CheckResult from quality_gate
        run_id: str = "",
        psi_threshold: float = 0.20,
        jsd_threshold: float = 0.15,
        baseline_name: str = "",
    ) -> "DriftReport":
        """Build a DriftReport from a QualityGate CheckResult."""
        details = check_result.details or {}
        return cls(
            run_id=run_id,
            blocked=check_result.blocked,
            severity=check_result.severity,
            message=check_result.message,
            max_psi=details.get("max_psi", 0.0),
            max_jsd=details.get("max_jsd", 0.0),
            feature_drifts=details.get("feature_drifts", {}),
            volume_drift=details.get("volume_drift", {}),
            schema_drift=details.get("schema_drift", {}),
            psi_threshold=psi_threshold,
            jsd_threshold=jsd_threshold,
            baseline_name=baseline_name,
        )

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "blocked": self.blocked,
            "severity": self.severity,
            "message": self.message,
            "max_psi": self.max_psi,
            "max_jsd": self.max_jsd,
            "psi_threshold": self.psi_threshold,
            "jsd_threshold": self.jsd_threshold,
            "baseline_name": self.baseline_name,
            "feature_drifts": self.feature_drifts,
            "volume_drift": self.volume_drift,
            "schema_drift": self.schema_drift,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_text(self) -> str:
        """Human-readable drift report."""
        lines = [
            "=" * 60,
            "DRIFT REPORT",
            "=" * 60,
            f"  Run ID     : {self.run_id}",
            f"  Timestamp  : {self.timestamp}",
            f"  Baseline   : {self.baseline_name or '(latest)'}",
            f"  Verdict    : {'BLOCKED' if self.blocked else 'PASSED'}",
            f"  Severity   : {self.severity.upper()}",
            f"  Message    : {self.message}",
            "",
            "-" * 60,
            "GLOBAL METRICS",
            "-" * 60,
            f"  Max PSI    : {self.max_psi:.4f}  (threshold: {self.psi_threshold})",
            f"  Max JSD    : {self.max_jsd:.4f}  (threshold: {self.jsd_threshold})",
            "",
        ]

        # Volume drift
        if self.volume_drift:
            lines.extend([
                "-" * 60,
                "VOLUME DRIFT",
                "-" * 60,
                f"  Baseline count : {self.volume_drift.get('baseline_count', '?')}",
                f"  Current count  : {self.volume_drift.get('current_count', '?')}",
                f"  Change rate    : {self.volume_drift.get('change_rate', 0):.1%}",
                "",
            ])

        # Schema drift
        if self.schema_drift:
            lines.extend([
                "-" * 60,
                "SCHEMA DRIFT",
                "-" * 60,
            ])
            added = self.schema_drift.get("added_fields", [])
            removed = self.schema_drift.get("removed_fields", [])
            if added:
                lines.append(f"  Added fields   : {', '.join(added)}")
            if removed:
                lines.append(f"  Removed fields : {', '.join(removed)}")
            if not added and not removed:
                lines.append("  No schema drift detected")
            lines.append("")

        # Feature-level drift
        if self.feature_drifts:
            lines.extend([
                "-" * 60,
                "FEATURE DRIFT",
                "-" * 60,
                f"  {'Feature':<20} {'Type':<12} {'PSI':<10} {'JSD':<10} {'Status'}",
                f"  {'─' * 20} {'─' * 12} {'─' * 10} {'─' * 10} {'─' * 10}",
            ])
            for feat, info in sorted(self.feature_drifts.items()):
                psi = info.get("psi", 0.0)
                jsd = info.get("jsd", 0.0)
                ftype = info.get("type", "?")
                status = "DRIFT" if psi > self.psi_threshold else (
                    "warn" if psi > self.psi_threshold * 0.5 else "ok"
                )
                lines.append(
                    f"  {feat:<20} {ftype:<12} {psi:<10.4f} {jsd:<10.4f} {status}"
                )

                # Extra detail for numeric features
                if ftype == "numeric":
                    bm = info.get("base_mean", "?")
                    cm = info.get("cur_mean", "?")
                    lines.append(f"    base_mean={bm}  cur_mean={cm}")
            lines.append("")

        lines.extend([
            "=" * 60,
            f"END OF DRIFT REPORT (run_id={self.run_id})",
            "=" * 60,
        ])
        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────

    def save(
        self, output_dir: str = "backend/data/quality_reports"
    ) -> Path:
        """
        Save drift report to disk as both JSON and text.

        Returns:
            Path to the saved JSON file.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"drift_report_{self.run_id or ts}"

        json_path = out / f"{stem}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

        text_path = out / f"{stem}.txt"
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(self.to_text())

        return json_path

    # ── Alert payload ─────────────────────────────────────────────

    def to_alert_payload(self) -> Dict[str, Any]:
        """Compact payload suitable for webhook/Slack alerts."""
        drifted_features = [
            f for f, info in self.feature_drifts.items()
            if info.get("psi", 0) > self.psi_threshold
        ]
        return {
            "title": f"Drift {'BLOCKED' if self.blocked else 'Warning'}: {self.run_id}",
            "severity": self.severity,
            "max_psi": round(self.max_psi, 4),
            "max_jsd": round(self.max_jsd, 4),
            "drifted_features": drifted_features,
            "volume_change": self.volume_drift.get("change_rate", 0),
            "schema_changes": bool(self.schema_drift),
            "blocked": self.blocked,
        }
