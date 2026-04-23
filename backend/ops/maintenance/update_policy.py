# backend/ops/maintenance/update_policy.py
"""
Update Policy Manager.

Manages:
- Pipeline component update schedules
- Crawler site-change detection
- Dependency update tracking
- Schema migration planning
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.maintenance.update")


class UpdatePolicy:
    """
    Defines and enforces update policies for pipeline components.

    Tracks component versions, update schedules, and
    recommends updates based on age and criticality.
    """

    DEFAULT_POLICIES = {
        "crawler_selectors": {
            "check_interval_days": 7,
            "max_age_days": 30,
            "auto_update": False,
            "criticality": "high",
            "description": "CSS/XPath selectors for job sites — break when sites change",
        },
        "dependencies": {
            "check_interval_days": 30,
            "max_age_days": 90,
            "auto_update": False,
            "criticality": "medium",
            "description": "Python packages and system dependencies",
        },
        "scoring_weights": {
            "check_interval_days": 90,
            "max_age_days": 365,
            "auto_update": False,
            "criticality": "high",
            "description": "SIMGR scoring weights and thresholds",
        },
        "taxonomy_data": {
            "check_interval_days": 30,
            "max_age_days": 180,
            "auto_update": False,
            "criticality": "medium",
            "description": "Career taxonomy and skill mappings",
        },
        "llm_prompts": {
            "check_interval_days": 14,
            "max_age_days": 60,
            "auto_update": False,
            "criticality": "medium",
            "description": "LLM prompt templates for explanation generation",
        },
    }

    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or Path("backend/data/update_state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    def check_updates_due(self) -> List[Dict[str, Any]]:
        """Return list of components that need updates."""
        due = []
        now = datetime.now()

        for component, policy in self.DEFAULT_POLICIES.items():
            last_check = self._state.get(component, {}).get("last_checked")
            last_update = self._state.get(component, {}).get("last_updated")

            check_due = True
            if last_check:
                last_dt = datetime.fromisoformat(last_check)
                check_due = (now - last_dt) > timedelta(days=policy["check_interval_days"])

            update_needed = False
            if last_update:
                update_dt = datetime.fromisoformat(last_update)
                update_needed = (now - update_dt) > timedelta(days=policy["max_age_days"])

            if check_due or update_needed:
                due.append({
                    "component": component,
                    "criticality": policy["criticality"],
                    "description": policy["description"],
                    "check_due": check_due,
                    "update_needed": update_needed,
                    "last_checked": last_check,
                    "last_updated": last_update,
                    "max_age_days": policy["max_age_days"],
                })

        # Sort by criticality
        order = {"high": 0, "medium": 1, "low": 2}
        due.sort(key=lambda x: order.get(x["criticality"], 3))
        return due

    def record_check(self, component: str) -> None:
        """Record that a component was checked."""
        if component not in self._state:
            self._state[component] = {}
        self._state[component]["last_checked"] = datetime.now().isoformat()
        self._save_state()

    def record_update(self, component: str, version: str = "") -> None:
        """Record that a component was updated."""
        if component not in self._state:
            self._state[component] = {}
        self._state[component]["last_updated"] = datetime.now().isoformat()
        self._state[component]["current_version"] = version
        self._save_state()
        logger.info(f"Component '{component}' updated to version '{version}'")

    def get_dashboard(self) -> Dict[str, Any]:
        """Get update status dashboard."""
        due = self.check_updates_due()
        return {
            "total_components": len(self.DEFAULT_POLICIES),
            "updates_due": len(due),
            "critical_due": sum(1 for d in due if d["criticality"] == "high"),
            "components": due,
            "checked_at": datetime.now().isoformat(),
        }

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self._state, indent=2))
