# backend/ops/sla/reporter.py
"""
SLA Reporter
============

Generates SLA compliance reports:
- Weekly SLA reports
- Monthly SLA reports
- Incident reports
- Export to PDF/CSV
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.ops.sla.contracts import SLAContract, SLAViolation, SLASeverity, SLAStatus
from backend.ops.sla.evaluator import SLAEvaluator

logger = logging.getLogger("ops.sla.reporter")


@dataclass
class SLAReportPeriod:
    """Report time period."""
    start: str
    end: str
    days: int
    
    @classmethod
    def weekly(cls, reference_date: Optional[datetime] = None) -> "SLAReportPeriod":
        """Create weekly period (last 7 days)."""
        end = reference_date or datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        return cls(start=start.isoformat(), end=end.isoformat(), days=7)
    
    @classmethod
    def monthly(cls, reference_date: Optional[datetime] = None) -> "SLAReportPeriod":
        """Create monthly period (last 30 days)."""
        end = reference_date or datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        return cls(start=start.isoformat(), end=end.isoformat(), days=30)
    
    @classmethod
    def custom(cls, start: datetime, end: datetime) -> "SLAReportPeriod":
        """Create custom period."""
        days = (end - start).days
        return cls(start=start.isoformat(), end=end.isoformat(), days=days)


@dataclass
class SLAReport:
    """SLA compliance report."""
    report_id: str
    report_type: str  # "weekly", "monthly", "custom"
    period: SLAReportPeriod
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Summary metrics
    overall_compliance: float = 1.0
    overall_status: SLAStatus = SLAStatus.HEALTHY
    
    # Violation summary
    total_violations: int = 0
    critical_violations: int = 0
    warning_violations: int = 0
    acknowledged_violations: int = 0
    
    # Per-contract breakdown
    contract_reports: List[Dict[str, Any]] = field(default_factory=list)
    
    # Time series data
    daily_compliance: List[Dict[str, Any]] = field(default_factory=list)
    
    # Trends
    violation_trend: str = "stable"  # "improving", "degrading", "stable"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "period": {
                "start": self.period.start,
                "end": self.period.end,
                "days": self.period.days,
            },
            "generated_at": self.generated_at,
            "summary": {
                "overall_compliance": round(self.overall_compliance, 4),
                "overall_status": self.overall_status.value,
                "total_violations": self.total_violations,
                "critical_violations": self.critical_violations,
                "warning_violations": self.warning_violations,
                "acknowledged_violations": self.acknowledged_violations,
                "violation_trend": self.violation_trend,
            },
            "contracts": self.contract_reports,
            "daily_compliance": self.daily_compliance,
        }


class SLAReporter:
    """
    SLA Report Generator.
    
    Generates:
    - Weekly SLA compliance reports
    - Monthly SLA compliance reports
    - Incident reports
    - CSV/JSON exports
    """
    
    def __init__(
        self,
        evaluator: Optional[SLAEvaluator] = None,
        output_dir: Optional[Path] = None,
    ):
        self._evaluator = evaluator
        self._output_dir = output_dir or Path("backend/data/ops/reports")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("SLAReporter initialized")
    
    def set_evaluator(self, evaluator: SLAEvaluator) -> None:
        """Set the evaluator instance."""
        self._evaluator = evaluator
    
    def generate_report(
        self,
        period: SLAReportPeriod,
        report_type: str = "custom",
    ) -> SLAReport:
        """Generate an SLA compliance report for the given period."""
        import hashlib
        
        report_id = hashlib.sha256(
            f"{report_type}:{period.start}:{period.end}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        report = SLAReport(
            report_id=report_id,
            report_type=report_type,
            period=period,
        )
        
        if not self._evaluator:
            return report
        
        # Get violations for the period
        violations = self._evaluator.get_recent_violations(
            hours=period.days * 24
        )
        
        # Filter to period
        violations = [
            v for v in violations
            if period.start <= v["timestamp"] <= period.end
        ]
        
        # Calculate summary
        report.total_violations = len(violations)
        report.critical_violations = len([v for v in violations if v["severity"] == "critical"])
        report.warning_violations = len([v for v in violations if v["severity"] == "warning"])
        report.acknowledged_violations = len([v for v in violations if v.get("acknowledged")])
        
        # Calculate overall compliance (simplified: 1 - (violations / expected_checks))
        expected_checks = period.days * 24  # Assuming hourly checks
        if expected_checks > 0:
            report.overall_compliance = max(0, 1 - (report.critical_violations / expected_checks))
        
        # Determine overall status
        if report.critical_violations > 0:
            report.overall_status = SLAStatus.BREACHED
        elif report.warning_violations > 0:
            report.overall_status = SLAStatus.AT_RISK
        else:
            report.overall_status = SLAStatus.HEALTHY
        
        # Generate per-contract reports
        report.contract_reports = self._generate_contract_reports(violations)
        
        # Generate daily compliance trend
        report.daily_compliance = self._generate_daily_trend(violations, period)
        
        # Determine trend
        report.violation_trend = self._determine_trend(violations, period)
        
        return report
    
    def _generate_contract_reports(
        self,
        violations: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Generate per-contract breakdown."""
        by_contract: Dict[str, List[Dict]] = {}
        for v in violations:
            by_contract.setdefault(v["contract_id"], []).append(v)
        
        reports = []
        for contract_id, contract_violations in by_contract.items():
            contract = self._evaluator.get_contract(contract_id) if self._evaluator else None
            
            critical = len([v for v in contract_violations if v["severity"] == "critical"])
            warning = len([v for v in contract_violations if v["severity"] == "warning"])
            
            reports.append({
                "contract_id": contract_id,
                "contract_name": contract.name if contract else "Unknown",
                "total_violations": len(contract_violations),
                "critical_violations": critical,
                "warning_violations": warning,
                "status": "breached" if critical > 0 else ("at_risk" if warning > 0 else "healthy"),
                "top_violations": [
                    {
                        "target": v["target_name"],
                        "count": 1,
                        "severity": v["severity"],
                    }
                    for v in contract_violations[:5]
                ],
            })
        
        return reports
    
    def _generate_daily_trend(
        self,
        violations: List[Dict[str, Any]],
        period: SLAReportPeriod,
    ) -> List[Dict[str, Any]]:
        """Generate daily compliance trend."""
        from collections import defaultdict
        
        daily_violations: Dict[str, int] = defaultdict(int)
        
        for v in violations:
            # Extract date from timestamp
            date = v["timestamp"][:10]  # YYYY-MM-DD
            daily_violations[date] += 1
        
        # Generate daily entries
        trend = []
        start_date = datetime.fromisoformat(period.start.replace("Z", "+00:00"))
        
        for i in range(period.days):
            date = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            violation_count = daily_violations.get(date, 0)
            compliance = max(0, 1 - (violation_count / 24))  # Assuming hourly checks
            
            trend.append({
                "date": date,
                "violations": violation_count,
                "compliance": round(compliance, 4),
            })
        
        return trend
    
    def _determine_trend(
        self,
        violations: List[Dict[str, Any]],
        period: SLAReportPeriod,
    ) -> str:
        """Determine if compliance is improving, degrading, or stable."""
        if len(violations) < 2:
            return "stable"
        
        # Compare first half to second half
        mid_point = datetime.fromisoformat(period.start.replace("Z", "+00:00")) + timedelta(days=period.days // 2)
        mid_str = mid_point.isoformat()
        
        first_half = len([v for v in violations if v["timestamp"] < mid_str])
        second_half = len([v for v in violations if v["timestamp"] >= mid_str])
        
        if second_half < first_half * 0.7:
            return "improving"
        elif second_half > first_half * 1.3:
            return "degrading"
        else:
            return "stable"
    
    def generate_weekly_report(self) -> SLAReport:
        """Generate weekly SLA report."""
        period = SLAReportPeriod.weekly()
        return self.generate_report(period, report_type="weekly")
    
    def generate_monthly_report(self) -> SLAReport:
        """Generate monthly SLA report."""
        period = SLAReportPeriod.monthly()
        return self.generate_report(period, report_type="monthly")
    
    def export_csv(self, report: SLAReport) -> str:
        """Export report to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(["SLA Compliance Report"])
        writer.writerow(["Report ID", report.report_id])
        writer.writerow(["Report Type", report.report_type])
        writer.writerow(["Period Start", report.period.start])
        writer.writerow(["Period End", report.period.end])
        writer.writerow(["Generated At", report.generated_at])
        writer.writerow([])
        
        # Summary
        writer.writerow(["Summary"])
        writer.writerow(["Overall Compliance", f"{report.overall_compliance:.2%}"])
        writer.writerow(["Overall Status", report.overall_status.value])
        writer.writerow(["Total Violations", report.total_violations])
        writer.writerow(["Critical Violations", report.critical_violations])
        writer.writerow(["Warning Violations", report.warning_violations])
        writer.writerow(["Trend", report.violation_trend])
        writer.writerow([])
        
        # Per-contract breakdown
        writer.writerow(["Contract Breakdown"])
        writer.writerow(["Contract ID", "Contract Name", "Total", "Critical", "Warning", "Status"])
        for contract in report.contract_reports:
            writer.writerow([
                contract["contract_id"],
                contract["contract_name"],
                contract["total_violations"],
                contract["critical_violations"],
                contract["warning_violations"],
                contract["status"],
            ])
        writer.writerow([])
        
        # Daily trend
        writer.writerow(["Daily Compliance"])
        writer.writerow(["Date", "Violations", "Compliance"])
        for day in report.daily_compliance:
            writer.writerow([day["date"], day["violations"], f"{day['compliance']:.2%}"])
        
        return output.getvalue()
    
    def export_json(self, report: SLAReport) -> str:
        """Export report to JSON format."""
        return json.dumps(report.to_dict(), indent=2)
    
    def save_report(
        self,
        report: SLAReport,
        formats: List[str] = None,
    ) -> Dict[str, Path]:
        """Save report to files."""
        formats = formats or ["json", "csv"]
        saved = {}
        
        base_name = f"sla_report_{report.report_type}_{report.report_id}"
        
        if "json" in formats:
            json_path = self._output_dir / f"{base_name}.json"
            json_path.write_text(self.export_json(report))
            saved["json"] = json_path
        
        if "csv" in formats:
            csv_path = self._output_dir / f"{base_name}.csv"
            csv_path.write_text(self.export_csv(report))
            saved["csv"] = csv_path
        
        logger.info(f"Saved SLA report: {base_name} in formats {list(saved.keys())}")
        return saved


# Global reporter instance
_reporter: Optional[SLAReporter] = None


def get_sla_reporter() -> SLAReporter:
    """Get or create the global SLA reporter instance."""
    global _reporter
    if _reporter is None:
        _reporter = SLAReporter()
    return _reporter
