# backend/risk/__init__.py
"""
Risk Module - SIMGR Stage 3 Compliant

Central risk assessment module for career decision support.
Implements DOC formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R

Components:
- RiskModel: Dropout and unemployment prediction
- CostModel: Education, time, and opportunity costs
- DataLoader: Dataset integration (unemployment, costs)
- PenaltyEngine: Central risk calculation
- Registry: Dynamic config management

CRITICAL: Risk is RAW value (high = bad).
          Risk is SUBTRACTED in final formula.
          NO INVERSION allowed.
"""

from .model import RiskModel, DropoutPredictor, UnemploymentPredictor
from .penalty import RiskPenaltyEngine, get_penalty_engine, compute_risk
from .data_loader import UnemploymentLoader, CostDataLoader, SectorRiskLoader
from .registry import RiskRegistry, get_registry

__all__ = [
    "RiskModel",
    "DropoutPredictor",
    "UnemploymentPredictor",
    "RiskPenaltyEngine",
    "get_penalty_engine",
    "compute_risk",
    "UnemploymentLoader",
    "CostDataLoader",
    "SectorRiskLoader",
    "RiskRegistry",
    "get_registry",
]

__version__ = "1.0.0"
