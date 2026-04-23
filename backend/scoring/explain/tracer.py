# backend/scoring/explain/tracer.py
"""
Score computation tracing for explainability.

Provides detailed tracing of how SIMGR scores are computed.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class ComponentTrace:
    """Trace for single component computation."""
    component_name: str
    score: float
    details: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class ScoringTrace:
    """Complete trace of scoring computation.

    Attributes:
        career_name: Career being scored
        user_summary: Summary of user profile
        components: List of component traces
        simgr_scores: SIMGR component scores
        total_score: Final weighted score
        weights_used: SIMGR weights used
        contributions: Component -> weight -> contribution mapping
        timestamp: When scoring occurred
    """
    career_name: str
    user_summary: Dict[str, Any]
    components: List[ComponentTrace] = field(default_factory=list)
    simgr_scores: Dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0
    weights_used: Dict[str, float] = field(default_factory=dict)
    contributions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def add_component(
        self,
        name: str,
        score: float,
        details: Dict[str, Any]
    ) -> None:
        """Add component trace."""
        trace = ComponentTrace(
            component_name=name,
            score=score,
            details=details
        )
        self.components.append(trace)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "career_name": self.career_name,
            "user_summary": self.user_summary,
            "components": [c.to_dict() for c in self.components],
            "simgr_scores": self.simgr_scores,
            "total_score": round(self.total_score, 4),
            "weights_used": self.weights_used,
            "timestamp": self.timestamp.isoformat(),
        }
    
    def to_readable(self) -> str:
        """Convert to human-readable format."""
        lines = [
            f"Score Trace for: {self.career_name}",
            f"Timestamp: {self.timestamp.isoformat()}",
            "",
            "User Summary:",
            f"  Skills: {self.user_summary.get('skill_count', 0)}",
            f"  Interests: {self.user_summary.get('interest_count', 0)}",
            "",
            "SIMGR Scores:",
        ]
        
        for key, val in self.simgr_scores.items():
            lines.append(f"  {key}: {val:.4f}")

        lines.append(f"  TOTAL: {self.total_score:.4f}")
        
        if self.components and self.weights_used:
            lines.append("")
            lines.append("Weights Used:")
            for key, val in self.weights_used.items():
                lines.append(f"  {key}: {round(val, 4)}")
        
        return "\n".join(lines)


class ScoringTracer:
    """Manages score tracing throughout computation."""
    
    def __init__(self, enabled: bool = True):
        """Initialize tracer.
        
        Args:
            enabled: Whether tracing is enabled
        """
        self.enabled = enabled
        self.current_trace: Optional[ScoringTrace] = None
    
    def start_trace(
        self,
        career_name: str,
        user_summary: Dict[str, Any]
    ) -> None:
        """Start tracing a score computation.
        
        Args:
            career_name: Career being scored
            user_summary: Summary of user profile
        """
        if not self.enabled:
            return
        
        self.current_trace = ScoringTrace(
            career_name=career_name,
            user_summary=user_summary
        )
    
    def trace_component(
        self,
        name: str,
        score: float,
        details: Dict[str, Any]
    ) -> None:
        """Trace a component score.
        
        Args:
            name: Component name
            score: Score value [0,1]
            details: Component details
        """
        if not self.enabled or not self.current_trace:
            return
        
        self.current_trace.add_component(name, score, details)
    
    def set_simgr_scores(self, scores: Dict[str, float]) -> None:
        """Set SIMGR component scores.
        
        Args:
            scores: Dict of SIMGR scores
        """
        if not self.enabled or not self.current_trace:
            return
        
        self.current_trace.simgr_scores = scores
    
    def set_total_score(
        self,
        total: float,
        weights: Dict[str, float]
    ) -> None:
        """Set total score and weights (GĐ7 compliant).
        
        Args:
            total: Final weighted score
            weights: Weights used
        """
        if not self.enabled or not self.current_trace:
            return
        
        self.current_trace.total_score = total
        self.current_trace.weights_used = weights
    
    def get_trace(self) -> Optional[ScoringTrace]:
        """Get current trace."""
        return self.current_trace
    
    def clear(self) -> None:
        """Clear current trace."""
        self.current_trace = None
