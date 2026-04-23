# backend/scoring/_core/__init__.py
"""
SIMGR Core - ISOLATED MODULE
============================

GĐ2 PHẦN C: Core Isolation

This module contains core scoring classes that MUST NOT be imported directly.
All access MUST go through MainController.

SECURITY NOTICE:
- Direct import from this module is BLOCKED outside controller
- Use MainController.dispatch() for all scoring operations
- Unauthorized imports will raise ImportError

Classes:
- SIMGRCalculator (moved from calculator.py)
- RankingEngine (moved from engine.py)  
- SIMGRScorer (moved from scoring.py)
"""

from backend.scoring.security.guards import guard_import, is_test_mode

# Guard against unauthorized imports
# This check runs when module is imported
if not is_test_mode():
    guard_import("backend.scoring._core")

# Only expose through __all__ - controlled access
__all__ = []  # Empty - no public exports

# Internal access for authorized modules only
def _get_calculator():
    """Internal: Get SIMGRCalculator class."""
    from backend.scoring.calculator import SIMGRCalculator
    return SIMGRCalculator

def _get_engine():
    """Internal: Get RankingEngine class."""
    from backend.scoring.engine import RankingEngine
    return RankingEngine

def _get_scorer():
    """Internal: Get SIMGRScorer class."""
    from backend.scoring.scoring import SIMGRScorer
    return SIMGRScorer
