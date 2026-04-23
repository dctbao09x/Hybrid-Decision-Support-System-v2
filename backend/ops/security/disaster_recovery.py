# backend/ops/security/disaster_recovery.py
"""
Disaster Recovery Plan for pipeline infrastructure.

Defines:
- Recovery Point Objective (RPO)
- Recovery Time Objective (RTO)
- Recovery procedures
- Failover protocols
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.security.dr")


class RecoveryStep:
    """A single step in the recovery procedure."""

    def __init__(
        self,
        order: int,
        title: str,
        description: str,
        command: str = "",
        estimated_minutes: float = 5.0,
        requires_manual: bool = False,
    ):
        self.order = order
        self.title = title
        self.description = description
        self.command = command
        self.estimated_minutes = estimated_minutes
        self.requires_manual = requires_manual

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "title": self.title,
            "description": self.description,
            "command": self.command,
            "estimated_minutes": self.estimated_minutes,
            "requires_manual": self.requires_manual,
        }


class DisasterRecoveryPlan:
    """
    Disaster Recovery Plan for the pipeline.

    RPO (Recovery Point Objective): How much data loss is acceptable
    RTO (Recovery Time Objective): How quickly must we recover
    """

    def __init__(
        self,
        rpo_hours: float = 6.0,   # Max 6 hours of data loss
        rto_hours: float = 2.0,   # Must recover within 2 hours
    ):
        self.rpo_hours = rpo_hours
        self.rto_hours = rto_hours
        self.scenarios: Dict[str, List[RecoveryStep]] = {}
        self._init_default_scenarios()

    def _init_default_scenarios(self) -> None:
        """Initialize default recovery scenarios."""

        # Scenario 1: Data Corruption
        self.scenarios["data_corruption"] = [
            RecoveryStep(1, "Stop Pipeline", "Immediately stop all pipeline stages", "python -m backend.ops.scripts.stop_pipeline"),
            RecoveryStep(2, "Identify Corruption", "Check data integrity hashes", "python -m backend.ops.scripts.verify_integrity"),
            RecoveryStep(3, "Locate Last Good Backup", "Find most recent valid backup", "python -m backend.ops.scripts.list_backups"),
            RecoveryStep(4, "Restore Data", "Restore from backup", "python -m backend.ops.scripts.restore_backup --latest"),
            RecoveryStep(5, "Validate Restored Data", "Run validation on restored data", "python -m backend.ops.scripts.validate_data"),
            RecoveryStep(6, "Resume Pipeline", "Restart pipeline from checkpoint", "python -m backend.ops.scripts.resume_pipeline"),
        ]

        # Scenario 2: Crawler Failure
        self.scenarios["crawler_failure"] = [
            RecoveryStep(1, "Check Browser Processes", "Kill zombie browser processes", "python -m backend.ops.scripts.kill_browsers"),
            RecoveryStep(2, "Check Resources", "Verify memory and disk space", "python -m backend.ops.scripts.check_resources"),
            RecoveryStep(3, "Clear Crawler State", "Reset crawler resume state", "python -m backend.ops.scripts.reset_crawler_state"),
            RecoveryStep(4, "Restart Crawlers", "Start crawlers with fresh state", "python -m backend.ops.scripts.start_crawlers"),
        ]

        # Scenario 3: Scoring Pipeline Failure
        self.scenarios["scoring_failure"] = [
            RecoveryStep(1, "Check Config", "Verify scoring config validity", "python -m backend.ops.scripts.validate_config"),
            RecoveryStep(2, "Rollback Config", "Revert to last known good config", "python -m backend.ops.scripts.rollback_config"),
            RecoveryStep(3, "Validate Input Data", "Check input data for scoring", "python -m backend.ops.scripts.validate_scoring_input"),
            RecoveryStep(4, "Re-run Scoring", "Re-execute scoring from checkpoint", "python -m backend.ops.scripts.rerun_scoring"),
        ]

        # Scenario 4: Full System Recovery
        self.scenarios["full_recovery"] = [
            RecoveryStep(1, "Environment Check", "Verify Python and dependencies", "python -m backend.ops.scripts.check_environment"),
            RecoveryStep(2, "Restore Config", "Restore all configurations", "python -m backend.ops.scripts.restore_config"),
            RecoveryStep(3, "Restore Data", "Restore latest data backup", "python -m backend.ops.scripts.restore_backup --latest"),
            RecoveryStep(4, "Verify Integrity", "Check all data integrity", "python -m backend.ops.scripts.verify_integrity"),
            RecoveryStep(5, "Test Components", "Run component health checks", "python -m backend.ops.scripts.health_check"),
            RecoveryStep(6, "Resume Pipeline", "Start pipeline from last checkpoint", "python -m backend.ops.scripts.resume_pipeline"),
            RecoveryStep(7, "Monitor Recovery", "Watch metrics for stability", "python -m backend.ops.scripts.monitor --duration=30m", 30),
        ]

    def get_scenario(self, name: str) -> List[Dict[str, Any]]:
        """Get recovery steps for a scenario."""
        steps = self.scenarios.get(name, [])
        return [s.to_dict() for s in steps]

    def list_scenarios(self) -> List[str]:
        """List available recovery scenarios."""
        return list(self.scenarios.keys())

    def estimate_recovery_time(self, scenario: str) -> float:
        """Estimate recovery time in minutes for a scenario."""
        steps = self.scenarios.get(scenario, [])
        return sum(s.estimated_minutes for s in steps)

    def get_plan_summary(self) -> Dict[str, Any]:
        """Get full DR plan summary."""
        return {
            "rpo_hours": self.rpo_hours,
            "rto_hours": self.rto_hours,
            "scenarios": {
                name: {
                    "steps": len(steps),
                    "estimated_minutes": sum(s.estimated_minutes for s in steps),
                    "requires_manual": any(s.requires_manual for s in steps),
                }
                for name, steps in self.scenarios.items()
            },
            "last_updated": datetime.now().isoformat(),
        }

    def export_plan(self, path: Optional[Path] = None) -> Path:
        """Export the full DR plan to a JSON file."""
        export_path = path or Path("backend/data/disaster_recovery_plan.json")
        export_path.parent.mkdir(parents=True, exist_ok=True)

        plan = {
            "title": "Pipeline Disaster Recovery Plan",
            "rpo_hours": self.rpo_hours,
            "rto_hours": self.rto_hours,
            "scenarios": {
                name: [s.to_dict() for s in steps]
                for name, steps in self.scenarios.items()
            },
            "exported_at": datetime.now().isoformat(),
        }

        export_path.write_text(json.dumps(plan, indent=2))
        logger.info(f"DR plan exported to {export_path}")
        return export_path
