# backend/ops/governance/reporting.py
"""
Reporting Module
================

Generates:
- Weekly SLA reports
- Monthly risk reports  
- Incident reports
- Executive summaries
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

logger = logging.getLogger("ops.governance.reporting")


@dataclass
class ReportMetadata:
    """Report metadata."""
    report_id: str
    report_type: str
    title: str
    generated_at: str
    period_start: str
    period_end: str
    generated_by: str = "system"


@dataclass
class IncidentReport:
    """Incident report data."""
    incident_id: str
    title: str
    severity: str  # "low", "medium", "high", "critical"
    status: str  # "open", "acknowledged", "resolved"
    occurred_at: str
    resolved_at: Optional[str] = None
    description: str = ""
    affected_services: List[str] = field(default_factory=list)
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    timeline: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "occurred_at": self.occurred_at,
            "resolved_at": self.resolved_at,
            "description": self.description,
            "affected_services": self.affected_services,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "timeline": self.timeline,
        }


@dataclass
class WeeklySLAReport:
    """Weekly SLA report."""
    metadata: ReportMetadata
    
    # Overall metrics
    overall_uptime: float = 1.0
    overall_compliance: float = 1.0
    total_requests: int = 0
    successful_requests: int = 0
    
    # SLA performance
    sla_violations: int = 0
    critical_violations: int = 0
    mean_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Daily breakdown
    daily_stats: List[Dict[str, Any]] = field(default_factory=list)
    
    # Incidents
    incidents: List[IncidentReport] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "report_id": self.metadata.report_id,
                "report_type": self.metadata.report_type,
                "title": self.metadata.title,
                "generated_at": self.metadata.generated_at,
                "period_start": self.metadata.period_start,
                "period_end": self.metadata.period_end,
            },
            "summary": {
                "overall_uptime": round(self.overall_uptime, 4),
                "overall_compliance": round(self.overall_compliance, 4),
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "success_rate": round(self.successful_requests / max(1, self.total_requests), 4),
            },
            "performance": {
                "sla_violations": self.sla_violations,
                "critical_violations": self.critical_violations,
                "latency": {
                    "mean_ms": round(self.mean_latency_ms, 2),
                    "p95_ms": round(self.p95_latency_ms, 2),
                    "p99_ms": round(self.p99_latency_ms, 2),
                },
            },
            "daily_breakdown": self.daily_stats,
            "incidents": [i.to_dict() for i in self.incidents],
            "recommendations": self.recommendations,
        }


@dataclass
class MonthlyRiskReport:
    """Monthly risk report."""
    metadata: ReportMetadata
    
    # Risk summary
    average_risk_score: float = 0.0
    peak_risk_score: float = 0.0
    risk_level_distribution: Dict[str, int] = field(default_factory=dict)
    
    # Component breakdown
    drift_contribution: float = 0.0
    latency_contribution: float = 0.0
    error_contribution: float = 0.0
    cost_contribution: float = 0.0
    
    # Mitigation summary
    total_mitigations: int = 0
    successful_mitigations: int = 0
    failed_mitigations: int = 0
    
    # Trends
    weekly_risk_trend: List[Dict[str, Any]] = field(default_factory=list)
    
    # Top risk events
    top_risk_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "report_id": self.metadata.report_id,
                "report_type": self.metadata.report_type,
                "title": self.metadata.title,
                "generated_at": self.metadata.generated_at,
                "period_start": self.metadata.period_start,
                "period_end": self.metadata.period_end,
            },
            "risk_summary": {
                "average_score": round(self.average_risk_score, 4),
                "peak_score": round(self.peak_risk_score, 4),
                "level_distribution": self.risk_level_distribution,
            },
            "component_breakdown": {
                "drift": round(self.drift_contribution, 4),
                "latency": round(self.latency_contribution, 4),
                "error_rate": round(self.error_contribution, 4),
                "cost_overrun": round(self.cost_contribution, 4),
            },
            "mitigations": {
                "total": self.total_mitigations,
                "successful": self.successful_mitigations,
                "failed": self.failed_mitigations,
                "success_rate": round(
                    self.successful_mitigations / max(1, self.total_mitigations), 4
                ),
            },
            "weekly_trend": self.weekly_risk_trend,
            "top_risk_events": self.top_risk_events,
            "recommendations": self.recommendations,
        }


class ReportGenerator:
    """
    Report Generator.
    
    Generates various operational reports:
    - Weekly SLA reports
    - Monthly risk reports
    - Incident reports
    - Executive summaries
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
    ):
        self._output_dir = output_dir or Path("backend/data/ops/reports")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("ReportGenerator initialized")
    
    def generate_weekly_sla_report(
        self,
        ops_pipeline=None,
        sla_evaluator=None,
        reference_date: Optional[datetime] = None,
    ) -> WeeklySLAReport:
        """Generate weekly SLA report."""
        import hashlib
        
        end_date = reference_date or datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)
        
        report_id = hashlib.sha256(
            f"weekly_sla:{start_date.isoformat()}:{end_date.isoformat()}".encode()
        ).hexdigest()[:12]
        
        metadata = ReportMetadata(
            report_id=report_id,
            report_type="weekly_sla",
            title=f"Weekly SLA Report - Week of {start_date.strftime('%Y-%m-%d')}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
        )
        
        report = WeeklySLAReport(metadata=metadata)
        
        # Get data from ops pipeline if available
        if ops_pipeline:
            self._populate_from_pipeline(report, ops_pipeline, start_date, end_date)
        
        # Get violations from SLA evaluator if available
        if sla_evaluator:
            self._populate_sla_violations(report, sla_evaluator)
        
        # Generate recommendations
        report.recommendations = self._generate_sla_recommendations(report)
        
        return report
    
    def _populate_from_pipeline(
        self,
        report: WeeklySLAReport,
        ops_pipeline,
        start_date: datetime,
        end_date: datetime,
    ) -> None:
        """Populate report from ops pipeline data."""
        try:
            # Get SLA metrics from pipeline
            metrics = ops_pipeline.get_sla_metrics()
            
            report.total_requests = metrics.get("total_requests", 0)
            report.successful_requests = int(
                report.total_requests * (1 - metrics.get("error_rate", 0))
            )
            report.mean_latency_ms = metrics.get("avg_latency_ms", 0)
            report.p95_latency_ms = metrics.get("p95_latency_ms", 0)
            report.p99_latency_ms = metrics.get("p99_latency_ms", 0)
            
            # Calculate uptime (simplified)
            if report.total_requests > 0:
                report.overall_uptime = report.successful_requests / report.total_requests
            
        except Exception as e:
            logger.warning(f"Failed to populate from pipeline: {e}")
    
    def _populate_sla_violations(
        self,
        report: WeeklySLAReport,
        sla_evaluator,
    ) -> None:
        """Populate SLA violations from evaluator."""
        try:
            violations = sla_evaluator.get_recent_violations(hours=168)  # 7 days
            report.sla_violations = len(violations)
            report.critical_violations = len([
                v for v in violations if v.get("severity") == "critical"
            ])
            
            # Calculate compliance
            if report.total_requests > 0:
                report.overall_compliance = max(
                    0, 1 - (report.critical_violations / report.total_requests)
                )
        except Exception as e:
            logger.warning(f"Failed to populate SLA violations: {e}")
    
    def _generate_sla_recommendations(self, report: WeeklySLAReport) -> List[str]:
        """Generate recommendations based on report data."""
        recommendations = []
        
        if report.overall_uptime < 0.999:
            recommendations.append(
                f"Uptime ({report.overall_uptime:.2%}) below target (99.9%). "
                "Consider implementing additional redundancy."
            )
        
        if report.p95_latency_ms > 500:
            recommendations.append(
                f"P95 latency ({report.p95_latency_ms:.0f}ms) exceeds 500ms threshold. "
                "Review slow queries and optimize critical paths."
            )
        
        if report.critical_violations > 5:
            recommendations.append(
                f"{report.critical_violations} critical SLA violations detected. "
                "Immediate investigation required."
            )
        
        if not recommendations:
            recommendations.append(
                "All SLA targets met. Continue monitoring for any degradation."
            )
        
        return recommendations
    
    def generate_monthly_risk_report(
        self,
        risk_manager=None,
        reference_date: Optional[datetime] = None,
    ) -> MonthlyRiskReport:
        """Generate monthly risk report."""
        import hashlib
        
        end_date = reference_date or datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        report_id = hashlib.sha256(
            f"monthly_risk:{start_date.isoformat()}:{end_date.isoformat()}".encode()
        ).hexdigest()[:12]
        
        metadata = ReportMetadata(
            report_id=report_id,
            report_type="monthly_risk",
            title=f"Monthly Risk Report - {start_date.strftime('%B %Y')}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
        )
        
        report = MonthlyRiskReport(metadata=metadata)
        
        if risk_manager:
            self._populate_risk_data(report, risk_manager)
        
        report.recommendations = self._generate_risk_recommendations(report)
        
        return report
    
    def _populate_risk_data(
        self,
        report: MonthlyRiskReport,
        risk_manager,
    ) -> None:
        """Populate risk data from risk manager."""
        try:
            history = risk_manager.get_risk_history(hours=720, limit=10000)  # 30 days
            
            if history:
                scores = [h["score"] for h in history]
                report.average_risk_score = sum(scores) / len(scores)
                report.peak_risk_score = max(scores)
                
                # Level distribution
                for h in history:
                    level = h["level"]
                    report.risk_level_distribution[level] = \
                        report.risk_level_distribution.get(level, 0) + 1
                
                # Component contributions (average)
                report.drift_contribution = sum(
                    h["components"]["drift"] for h in history
                ) / len(history)
                report.latency_contribution = sum(
                    h["components"]["latency"] for h in history
                ) / len(history)
                report.error_contribution = sum(
                    h["components"]["error_rate"] for h in history
                ) / len(history)
                report.cost_contribution = sum(
                    h["components"]["cost_overrun"] for h in history
                ) / len(history)
                
                # Top risk events
                sorted_history = sorted(history, key=lambda x: x["score"], reverse=True)
                report.top_risk_events = sorted_history[:10]
            
            # Mitigation history
            mitigations = risk_manager.get_mitigation_history(hours=720, limit=1000)
            report.total_mitigations = len(mitigations)
            report.successful_mitigations = len([
                m for m in mitigations if m["status"] == "completed"
            ])
            report.failed_mitigations = len([
                m for m in mitigations if m["status"] == "failed"
            ])
            
        except Exception as e:
            logger.warning(f"Failed to populate risk data: {e}")
    
    def _generate_risk_recommendations(self, report: MonthlyRiskReport) -> List[str]:
        """Generate recommendations based on risk report."""
        recommendations = []
        
        if report.average_risk_score > 0.5:
            recommendations.append(
                f"Average risk score ({report.average_risk_score:.2f}) is elevated. "
                "Review system stability and implement preventive measures."
            )
        
        if report.peak_risk_score > 0.8:
            recommendations.append(
                f"Peak risk score ({report.peak_risk_score:.2f}) indicates critical events. "
                "Conduct post-incident reviews."
            )
        
        # Find dominant risk component
        components = {
            "drift": report.drift_contribution,
            "latency": report.latency_contribution,
            "error_rate": report.error_contribution,
            "cost_overrun": report.cost_contribution,
        }
        top_component = max(components, key=components.get)
        
        if components[top_component] > 0.3:
            recommendations.append(
                f"{top_component.replace('_', ' ').title()} is the primary risk driver. "
                f"Focus optimization efforts on this area."
            )
        
        if report.failed_mitigations > 0:
            success_rate = report.successful_mitigations / max(1, report.total_mitigations)
            if success_rate < 0.9:
                recommendations.append(
                    f"Mitigation success rate ({success_rate:.0%}) below target. "
                    "Review and refine mitigation procedures."
                )
        
        if not recommendations:
            recommendations.append(
                "Risk levels within acceptable bounds. Continue monitoring."
            )
        
        return recommendations
    
    def generate_incident_report(
        self,
        incident_id: str,
        title: str,
        severity: str,
        occurred_at: str,
        description: str,
        affected_services: List[str],
        root_cause: Optional[str] = None,
        resolution: Optional[str] = None,
    ) -> IncidentReport:
        """Generate a single incident report."""
        return IncidentReport(
            incident_id=incident_id,
            title=title,
            severity=severity,
            status="open" if not resolution else "resolved",
            occurred_at=occurred_at,
            resolved_at=datetime.now(timezone.utc).isoformat() if resolution else None,
            description=description,
            affected_services=affected_services,
            root_cause=root_cause,
            resolution=resolution,
        )
    
    def export_to_json(self, report) -> str:
        """Export any report to JSON."""
        if hasattr(report, "to_dict"):
            return json.dumps(report.to_dict(), indent=2)
        return json.dumps(report, indent=2)
    
    def export_to_csv(self, report) -> str:
        """Export report to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        if isinstance(report, WeeklySLAReport):
            return self._export_sla_report_csv(report)
        elif isinstance(report, MonthlyRiskReport):
            return self._export_risk_report_csv(report)
        else:
            return self.export_to_json(report)
    
    def _export_sla_report_csv(self, report: WeeklySLAReport) -> str:
        """Export SLA report to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["Weekly SLA Report"])
        writer.writerow(["Report ID", report.metadata.report_id])
        writer.writerow(["Period", f"{report.metadata.period_start} to {report.metadata.period_end}"])
        writer.writerow([])
        
        writer.writerow(["Summary"])
        writer.writerow(["Overall Uptime", f"{report.overall_uptime:.2%}"])
        writer.writerow(["Overall Compliance", f"{report.overall_compliance:.2%}"])
        writer.writerow(["Total Requests", report.total_requests])
        writer.writerow(["Successful Requests", report.successful_requests])
        writer.writerow([])
        
        writer.writerow(["Performance"])
        writer.writerow(["SLA Violations", report.sla_violations])
        writer.writerow(["Critical Violations", report.critical_violations])
        writer.writerow(["Mean Latency (ms)", f"{report.mean_latency_ms:.2f}"])
        writer.writerow(["P95 Latency (ms)", f"{report.p95_latency_ms:.2f}"])
        writer.writerow(["P99 Latency (ms)", f"{report.p99_latency_ms:.2f}"])
        writer.writerow([])
        
        writer.writerow(["Recommendations"])
        for rec in report.recommendations:
            writer.writerow([rec])
        
        return output.getvalue()
    
    def _export_risk_report_csv(self, report: MonthlyRiskReport) -> str:
        """Export risk report to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["Monthly Risk Report"])
        writer.writerow(["Report ID", report.metadata.report_id])
        writer.writerow(["Period", f"{report.metadata.period_start} to {report.metadata.period_end}"])
        writer.writerow([])
        
        writer.writerow(["Risk Summary"])
        writer.writerow(["Average Risk Score", f"{report.average_risk_score:.4f}"])
        writer.writerow(["Peak Risk Score", f"{report.peak_risk_score:.4f}"])
        writer.writerow([])
        
        writer.writerow(["Level Distribution"])
        for level, count in report.risk_level_distribution.items():
            writer.writerow([level, count])
        writer.writerow([])
        
        writer.writerow(["Component Breakdown"])
        writer.writerow(["Drift", f"{report.drift_contribution:.4f}"])
        writer.writerow(["Latency", f"{report.latency_contribution:.4f}"])
        writer.writerow(["Error Rate", f"{report.error_contribution:.4f}"])
        writer.writerow(["Cost Overrun", f"{report.cost_contribution:.4f}"])
        writer.writerow([])
        
        writer.writerow(["Mitigations"])
        writer.writerow(["Total", report.total_mitigations])
        writer.writerow(["Successful", report.successful_mitigations])
        writer.writerow(["Failed", report.failed_mitigations])
        writer.writerow([])
        
        writer.writerow(["Recommendations"])
        for rec in report.recommendations:
            writer.writerow([rec])
        
        return output.getvalue()
    
    def save_report(
        self,
        report,
        formats: List[str] = None,
    ) -> Dict[str, Path]:
        """Save report to files."""
        formats = formats or ["json", "csv"]
        saved = {}
        
        if hasattr(report, "metadata"):
            base_name = f"{report.metadata.report_type}_{report.metadata.report_id}"
        else:
            base_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if "json" in formats:
            json_path = self._output_dir / f"{base_name}.json"
            json_path.write_text(self.export_to_json(report))
            saved["json"] = json_path
        
        if "csv" in formats:
            csv_path = self._output_dir / f"{base_name}.csv"
            csv_path.write_text(self.export_to_csv(report))
            saved["csv"] = csv_path
        
        logger.info(f"Saved report: {base_name}")
        return saved


# Global report generator instance
_report_generator: Optional[ReportGenerator] = None


def get_report_generator() -> ReportGenerator:
    """Get or create the global report generator instance."""
    global _report_generator
    if _report_generator is None:
        _report_generator = ReportGenerator()
    return _report_generator
