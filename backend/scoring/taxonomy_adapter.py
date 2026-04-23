"""
Scoring taxonomy adapter (vocabulary normalization).

Provides deterministic normalization of user inputs via taxonomy system.
"""

from __future__ import annotations

from typing import Iterable, List

try:
    from backend.taxonomy.facade import taxonomy
except ImportError:
    # Fallback if taxonomy not available
    from typing import Optional
    
    class MockTaxonomy:
        """Fallback taxonomy for testing."""
        
        def resolve_skill_list(
            self,
            values: Iterable[str],
            return_ids: bool = False
        ) -> List[str]:
            """Normalize skills (fallback)."""
            if not values:
                return []
            if isinstance(values, (set, tuple)):
                values = list(values)
            return [
                str(v).lower().strip()
                for v in values if v
            ]
        
        def resolve_interest_list(
            self,
            values: Iterable[str],
            return_ids: bool = False
        ) -> List[str]:
            """Normalize interests (fallback)."""
            if not values:
                return []
            if isinstance(values, (set, tuple)):
                values = list(values)
            return [
                str(v).lower().strip()
                for v in values if v
            ]
        
        def resolve_education(
            self,
            value: Optional[str],
            return_id: bool = False
        ) -> str:
            """Normalize education level (fallback)."""
            if not value:
                return "unknown"
            return str(value).lower().strip() or "unknown"
    
    taxonomy = MockTaxonomy()


def normalize_skill_list(values: Iterable[str]) -> List[str]:
    """Normalize skills via taxonomy.
    
    Args:
        values: Skill names
    
    Returns:
        Normalized skill list
    """
    return taxonomy.resolve_skill_list(values or [], return_ids=False)


def normalize_interest_list(values: Iterable[str]) -> List[str]:
    """Normalize interests via taxonomy.
    
    Args:
        values: Interest names
    
    Returns:
        Normalized interest list
    """
    return taxonomy.resolve_interest_list(values or [], return_ids=False)


def normalize_education(value: str) -> str:
    """Normalize education level via taxonomy.
    
    Args:
        value: Education level
    
    Returns:
        Normalized education level
    """
    if not value:
        return "unknown"
    label = taxonomy.resolve_education(value, return_id=False)
    if str(label).lower() == "unknown":
        return "unknown"
    return label

