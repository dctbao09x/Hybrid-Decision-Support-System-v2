# backend/ops - MLOps & DataOps Infrastructure
# Automation, monitoring, quality control, and reliability

from backend.ops.integration import OpsHub

# Cost & Budget Governance
from backend.ops.cost import (
    BudgetManager,
    CostEnforcementEngine,
    CostIntelligence,
    get_budget_manager,
    get_enforcement_engine,
    get_cost_intelligence,
)

# Incident Management
from backend.ops.incident import (
    IncidentManager,
    get_incident_manager,
)

# Kill-Switch Controller
from backend.ops.killswitch import (
    KillSwitchController,
    KillSwitchAPI,
    get_killswitch,
    get_killswitch_api,
)

# Integrated Governance
from backend.ops.governance import (
    GovernanceCoordinator,
    get_governance_coordinator,
)

__all__ = [
    "OpsHub",
    # Cost
    "BudgetManager",
    "CostEnforcementEngine",
    "CostIntelligence",
    "get_budget_manager",
    "get_enforcement_engine",
    "get_cost_intelligence",
    # Incident
    "IncidentManager",
    "get_incident_manager",
    # Kill-Switch
    "KillSwitchController",
    "KillSwitchAPI",
    "get_killswitch",
    "get_killswitch_api",
    # Governance
    "GovernanceCoordinator",
    "get_governance_coordinator",
]
#
# Modules:
#   A. orchestration  - Pipeline scheduling, checkpoints, rollback, retry
#   B. resource        - Browser monitoring, leak detection, concurrency, bottlenecks
#   C. quality         - Schema validation, completeness, outliers, drift, source reliability
#   D. versioning      - Dataset versioning, config versioning, snapshots, reproducibility
#   E. tests           - Unit, integration, E2E, regression test suites
#   F. monitoring      - Health checks, SLA monitoring, alerts, anomaly detection
#   G. security        - Secret management, access logging, backup, disaster recovery
#   H. maintenance     - Update policy, dependency management, retention, audit trail
#   I. cost            - Budget management, cost tracking, enforcement, intelligence
#   J. incident        - Incident lifecycle, RCA, playbooks, postmortems
#   K. killswitch      - Emergency kill-switch, safe mode, auto-triggers
#   L. governance      - Integrated governance coordination
