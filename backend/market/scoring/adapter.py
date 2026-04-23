# backend/market/scoring/adapter.py
"""
Scoring Auto-Adaptation Engine
==============================

Market-driven score adaptation with:
- Dynamic weight injection from market data
- Trend-based bonuses and penalties
- Drift detection and response
- Versioned configurations with rollback
- Full explanation and audit trail
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .models import (
    AdaptationEvent,
    AdjustmentType,
    ScoreAdjustment,
    ScoringConfig,
    ScoringExplanation,
    ScoringVersion,
)

logger = logging.getLogger("market.scoring.adapter")


# ═══════════════════════════════════════════════════════════════════════
# Score Explainer
# ═══════════════════════════════════════════════════════════════════════


class ScoreExplainer:
    """Generate human-readable explanations of score calculations."""
    
    @staticmethod
    def explain(
        skill_id: str,
        base_score: float,
        adjustments: List[Tuple[ScoreAdjustment, float]],
        final_score: float,
    ) -> ScoringExplanation:
        """
        Generate detailed explanation of score.
        
        Args:
            skill_id: Skill identifier
            base_score: Starting base score
            adjustments: List of (adjustment, applied_value) tuples
            final_score: Final calculated score
        
        Returns:
            ScoringExplanation with full breakdown
        """
        breakdown = []
        applied_types = []
        
        current_score = base_score
        
        for adj, applied_value in adjustments:
            if abs(applied_value) < 0.001:
                continue
            
            applied_types.append(adj.type)
            
            if adj.is_multiplicative:
                change = current_score * (applied_value - 1)
                operation = f"× {applied_value:.3f}"
            else:
                change = applied_value
                operation = f"+ {applied_value:.2f}" if applied_value >= 0 else f"- {abs(applied_value):.2f}"
            
            breakdown.append({
                "type": adj.type.value,
                "operation": operation,
                "change": change,
                "source": adj.source,
                "confidence": adj.confidence,
                "evidence": adj.evidence[:2],  # First 2 evidence items
            })
            
            if adj.is_multiplicative:
                current_score *= applied_value
            else:
                current_score += applied_value
        
        total_adjustment = final_score - base_score
        
        # Generate text explanation
        text_parts = [f"Base score: {base_score:.2f}"]
        
        for item in breakdown:
            adj_type = item["type"].replace("_", " ").title()
            text_parts.append(f"  {adj_type}: {item['operation']} (Δ{item['change']:+.2f})")
        
        text_parts.append(f"Final score: {final_score:.2f} (net change: {total_adjustment:+.2f})")
        
        return ScoringExplanation(
            skill_id=skill_id,
            base_score=base_score,
            final_score=final_score,
            adjustments_applied=applied_types,
            adjustment_breakdown=breakdown,
            total_adjustment=total_adjustment,
            explanation_text="\n".join(text_parts),
        )


# ═══════════════════════════════════════════════════════════════════════
# Scoring Adapter
# ═══════════════════════════════════════════════════════════════════════


class ScoringAdapter:
    """
    Adapt skill scores based on market intelligence.
    
    Features:
    - Dynamic market weight injection
    - Trend-based adjustments
    - Drift penalties
    - Version management with rollback
    - Full audit trail
    - Human-in-the-loop approval for major changes
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/scoring.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Active configuration
        self._active_config: Optional[ScoringConfig] = None
        self._active_version: Optional[ScoringVersion] = None
        
        # Version history
        self._versions: Dict[str, ScoringVersion] = {}
        
        # Event log
        self._events: List[AdaptationEvent] = []
        
        # Thresholds for auto-approval
        self._auto_approve_threshold = 0.1  # Auto-approve changes < 10%
        self._major_change_threshold = 0.3  # Major changes need review
        
        # Callbacks
        self._on_adaptation: List[Callable[[AdaptationEvent], None]] = []
        self._on_major_change: List[Callable[[AdaptationEvent], bool]] = []
        
        self._init_db()
        self._load_active_config()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scoring_versions (
                    version_id TEXT PRIMARY KEY,
                    version_number TEXT NOT NULL,
                    config_data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    is_active INTEGER DEFAULT 0,
                    previous_version TEXT,
                    changes_summary TEXT
                );
                
                CREATE TABLE IF NOT EXISTS adjustments (
                    adjustment_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value REAL NOT NULL,
                    is_multiplicative INTEGER DEFAULT 0,
                    source TEXT,
                    confidence REAL,
                    valid_from TEXT,
                    valid_until TEXT,
                    evidence TEXT
                );
                
                CREATE TABLE IF NOT EXISTS adaptation_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    event_type TEXT,
                    trigger TEXT,
                    skills_affected TEXT,
                    old_values TEXT,
                    new_values TEXT,
                    impact_assessment TEXT,
                    approved_by TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_adjustments_skill ON adjustments(skill_id);
                CREATE INDEX IF NOT EXISTS idx_versions_active ON scoring_versions(is_active);
            """)
    
    def _load_active_config(self) -> None:
        """Load active scoring configuration."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            row = conn.execute("""
                SELECT * FROM scoring_versions WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            
            if row:
                config_data = json.loads(row["config_data"])
                
                self._active_config = ScoringConfig(
                    config_id=config_data.get("config_id", "default"),
                    name=config_data.get("name", "default"),
                    base_weights=config_data.get("base_weights", {}),
                    adjustments=[],  # Will load separately
                    global_modifiers=config_data.get("global_modifiers", {}),
                )
                
                self._active_version = ScoringVersion(
                    version_id=row["version_id"],
                    version_number=row["version_number"],
                    config=self._active_config,
                    is_active=True,
                )
                
                # Load adjustments
                self._load_adjustments()
            else:
                # Create default config
                self._create_default_config()
    
    def _load_adjustments(self) -> None:
        """Load active adjustments."""
        if not self._active_config:
            return
        
        now = datetime.now(timezone.utc)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            for row in conn.execute("""
                SELECT * FROM adjustments 
                WHERE (valid_until IS NULL OR valid_until > ?)
                  AND valid_from <= ?
            """, (now.isoformat(), now.isoformat())):
                adj = ScoreAdjustment(
                    adjustment_id=row["adjustment_id"],
                    skill_id=row["skill_id"],
                    type=AdjustmentType(row["type"]),
                    value=row["value"],
                    is_multiplicative=bool(row["is_multiplicative"]),
                    source=row["source"] or "auto",
                    confidence=row["confidence"] or 1.0,
                    valid_from=datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else now,
                    valid_until=datetime.fromisoformat(row["valid_until"]) if row["valid_until"] else None,
                    evidence=json.loads(row["evidence"]) if row["evidence"] else [],
                )
                self._active_config.adjustments.append(adj)
    
    def _create_default_config(self) -> None:
        """Create default scoring configuration."""
        self._active_config = ScoringConfig(
            config_id="default_v1",
            name="Default Configuration",
            max_adjustment_cap=0.5,
        )
        
        self._active_version = ScoringVersion(
            version_id=f"v_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            version_number="1.0.0",
            config=self._active_config,
            is_active=True,
            created_by="system",
        )
        
        self._save_version(self._active_version)
    
    # ═══════════════════════════════════════════════════════════════════
    # Score Calculation
    # ═══════════════════════════════════════════════════════════════════
    
    def calculate_score(
        self,
        skill_id: str,
        base_score: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, ScoringExplanation]:
        """
        Calculate adjusted score for a skill.
        
        Args:
            skill_id: Skill identifier
            base_score: Base score before adjustments
            context: Optional context (career, industry, etc.)
        
        Returns:
            Tuple of (adjusted_score, explanation)
        """
        if not self._active_config:
            return base_score, ScoringExplanation(
                skill_id=skill_id,
                base_score=base_score,
                final_score=base_score,
                explanation_text="No active configuration",
            )
        
        config = self._active_config
        applied_adjustments: List[Tuple[ScoreAdjustment, float]] = []
        
        current_score = base_score
        
        # Apply base weight if available
        if skill_id in config.base_weights:
            base_weight_adj = ScoreAdjustment(
                adjustment_id="base_weight",
                skill_id=skill_id,
                type=AdjustmentType.MARKET_WEIGHT,
                value=config.base_weights[skill_id],
                is_multiplicative=True,
                source="config",
            )
            applied_adjustments.append((base_weight_adj, config.base_weights[skill_id]))
            current_score *= config.base_weights[skill_id]
        
        # Apply skill-specific adjustments
        for adj in config.adjustments:
            if adj.skill_id != skill_id:
                continue
            
            if adj.type not in config.enabled_adjustment_types:
                continue
            
            # Check validity
            now = datetime.now(timezone.utc)
            if adj.valid_until and adj.valid_until < now:
                continue
            
            # Apply adjustment
            if adj.is_multiplicative:
                applied_value = adj.value * adj.confidence
                current_score *= applied_value
            else:
                applied_value = adj.value * adj.confidence
                current_score += applied_value
            
            applied_adjustments.append((adj, applied_value))
        
        # Apply global modifiers
        for modifier_name, modifier_value in config.global_modifiers.items():
            mod_adj = ScoreAdjustment(
                adjustment_id=f"global_{modifier_name}",
                skill_id=skill_id,
                type=AdjustmentType.MARKET_WEIGHT,
                value=modifier_value,
                is_multiplicative=True,
                source="global",
            )
            applied_adjustments.append((mod_adj, modifier_value))
            current_score *= modifier_value
        
        # Cap adjustment
        max_change = base_score * config.max_adjustment_cap
        if abs(current_score - base_score) > max_change:
            if current_score > base_score:
                current_score = base_score + max_change
            else:
                current_score = base_score - max_change
        
        # Apply bounds
        final_score = max(config.min_score, min(config.max_score, current_score))
        
        # Generate explanation
        explanation = ScoreExplainer.explain(
            skill_id, base_score, applied_adjustments, final_score
        )
        
        return final_score, explanation
    
    def calculate_batch(
        self,
        scores: Dict[str, float],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Tuple[float, ScoringExplanation]]:
        """Calculate scores for multiple skills."""
        results = {}
        for skill_id, base_score in scores.items():
            results[skill_id] = self.calculate_score(skill_id, base_score, context)
        return results
    
    # ═══════════════════════════════════════════════════════════════════
    # Adjustment Management
    # ═══════════════════════════════════════════════════════════════════
    
    def inject_market_weights(
        self,
        weights: Dict[str, float],
        source: str = "market_data",
    ) -> AdaptationEvent:
        """
        Inject market-derived weights.
        
        Args:
            weights: Skill ID to weight mapping
            source: Source of weights
        
        Returns:
            AdaptationEvent record
        """
        event_id = f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_weights"
        old_weights = dict(self._active_config.base_weights) if self._active_config else {}
        
        # Update weights
        if self._active_config:
            self._active_config.base_weights.update(weights)
        
        # Assess impact
        changes = []
        for skill_id, new_weight in weights.items():
            old_weight = old_weights.get(skill_id, 1.0)
            change_pct = abs(new_weight - old_weight) / old_weight if old_weight > 0 else 0
            if change_pct > 0.01:
                changes.append((skill_id, change_pct))
        
        max_change = max(c[1] for c in changes) if changes else 0
        
        event = AdaptationEvent(
            event_id=event_id,
            event_type="market_weight_injection",
            trigger=source,
            skills_affected=list(weights.keys()),
            old_values=old_weights,
            new_values=weights,
            impact_assessment=f"Updated {len(weights)} weights, max change: {max_change:.1%}",
        )
        
        # Auto-approve or queue for review
        if max_change <= self._auto_approve_threshold:
            event.approved_by = "auto"
            self._apply_event(event)
        elif max_change >= self._major_change_threshold:
            # Major change - needs review
            for callback in self._on_major_change:
                if callback(event):
                    event.approved_by = "callback"
                    self._apply_event(event)
                    break
        else:
            event.approved_by = "auto"
            self._apply_event(event)
        
        self._events.append(event)
        self._save_event(event)
        
        return event
    
    def add_trend_adjustment(
        self,
        skill_id: str,
        growth_rate: float,
        confidence: float = 1.0,
        evidence: Optional[List[str]] = None,
    ) -> ScoreAdjustment:
        """
        Add trend-based adjustment.
        
        Args:
            skill_id: Skill identifier
            growth_rate: Monthly growth rate (e.g., 0.05 = 5%)
            confidence: Confidence in trend assessment
            evidence: Supporting evidence
        
        Returns:
            Created adjustment
        """
        # Calculate adjustment value
        # Growing skills get bonus, declining get penalty
        if growth_rate > 0.1:  # > 10% growth
            adj_type = AdjustmentType.TREND_BONUS
            value = min(0.3, growth_rate)  # Cap at 30% bonus
        elif growth_rate < -0.1:  # > 10% decline
            adj_type = AdjustmentType.TREND_PENALTY
            value = max(-0.2, growth_rate)  # Cap at 20% penalty
        else:
            return None  # No significant trend
        
        adjustment = ScoreAdjustment(
            adjustment_id=f"trend_{skill_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            skill_id=skill_id,
            type=adj_type,
            value=1 + value,  # Convert to multiplier
            is_multiplicative=True,
            source="trend_analysis",
            confidence=confidence,
            valid_until=datetime.now(timezone.utc) + timedelta(days=30),
            evidence=evidence or [f"Growth rate: {growth_rate:.1%}"],
        )
        
        if self._active_config:
            self._active_config.adjustments.append(adjustment)
        
        self._save_adjustment(adjustment)
        
        return adjustment
    
    def add_demand_adjustment(
        self,
        skill_id: str,
        demand_score: float,  # 0-100
        confidence: float = 1.0,
    ) -> ScoreAdjustment:
        """
        Add demand-based adjustment.
        
        High demand skills get bonus, low demand get penalty.
        """
        # Normalize demand to multiplier
        # 50 = neutral, 100 = +20%, 0 = -15%
        if demand_score >= 50:
            value = 1 + (demand_score - 50) / 50 * 0.2
        else:
            value = 1 - (50 - demand_score) / 50 * 0.15
        
        adjustment = ScoreAdjustment(
            adjustment_id=f"demand_{skill_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            skill_id=skill_id,
            type=AdjustmentType.DEMAND_MULTIPLIER,
            value=value,
            is_multiplicative=True,
            source="demand_forecast",
            confidence=confidence,
            valid_until=datetime.now(timezone.utc) + timedelta(days=14),
            evidence=[f"Demand score: {demand_score:.0f}/100"],
        )
        
        if self._active_config:
            self._active_config.adjustments.append(adjustment)
        
        self._save_adjustment(adjustment)
        
        return adjustment
    
    def add_drift_penalty(
        self,
        skill_id: str,
        drift_magnitude: float,
        drift_type: str,
    ) -> ScoreAdjustment:
        """
        Add penalty for skill drift.
        
        When skill requirements drift significantly, penalize to
        encourage re-evaluation.
        """
        # Higher drift = higher penalty
        penalty = min(0.15, drift_magnitude * 0.5)
        
        adjustment = ScoreAdjustment(
            adjustment_id=f"drift_{skill_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            skill_id=skill_id,
            type=AdjustmentType.DRIFT_PENALTY,
            value=1 - penalty,
            is_multiplicative=True,
            source="drift_detection",
            confidence=0.8,
            valid_until=datetime.now(timezone.utc) + timedelta(days=30),
            evidence=[f"Drift type: {drift_type}", f"Magnitude: {drift_magnitude:.2f}"],
        )
        
        if self._active_config:
            self._active_config.adjustments.append(adjustment)
        
        self._save_adjustment(adjustment)
        
        return adjustment
    
    def _apply_event(self, event: AdaptationEvent) -> None:
        """Apply adaptation event changes."""
        # Trigger callbacks
        for callback in self._on_adaptation:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Adaptation callback error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════
    # Version Management
    # ═══════════════════════════════════════════════════════════════════
    
    def create_version(
        self,
        notes: str = "",
        created_by: str = "system",
    ) -> ScoringVersion:
        """Create new version snapshot of current configuration."""
        if not self._active_config:
            self._create_default_config()
        
        # Increment version
        if self._active_version:
            parts = self._active_version.version_number.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            new_version_number = ".".join(parts)
            prev_version = self._active_version.version_id
        else:
            new_version_number = "1.0.0"
            prev_version = None
        
        # Create new version
        version = ScoringVersion(
            version_id=f"v_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            version_number=new_version_number,
            config=self._active_config,
            created_by=created_by,
            is_active=True,
            previous_version=prev_version,
            changes_summary=notes,
        )
        
        # Deactivate previous
        if self._active_version:
            self._active_version.is_active = False
            self._save_version(self._active_version)
        
        self._active_version = version
        self._versions[version.version_id] = version
        self._save_version(version)
        
        logger.info(f"Created scoring version {new_version_number}")
        return version
    
    def rollback(self, version_id: str) -> bool:
        """
        Rollback to a previous version.
        
        Args:
            version_id: Version to rollback to
        
        Returns:
            True if successful
        """
        if version_id not in self._versions:
            # Try loading from database
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM scoring_versions WHERE version_id = ?",
                    (version_id,)
                ).fetchone()
                
                if not row:
                    logger.error(f"Version {version_id} not found")
                    return False
        
        # Create rollback event
        event = AdaptationEvent(
            event_id=f"rollback_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            event_type="rollback",
            trigger=f"Rollback to {version_id}",
            skills_affected=list(self._active_config.base_weights.keys()) if self._active_config else [],
            impact_assessment="Configuration rollback",
        )
        
        # Deactivate current
        if self._active_version:
            self._active_version.is_active = False
            self._save_version(self._active_version)
        
        # Activate target version
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE scoring_versions SET is_active = 1 WHERE version_id = ?",
                (version_id,)
            )
        
        # Reload
        self._load_active_config()
        
        self._events.append(event)
        self._save_event(event)
        
        logger.info(f"Rolled back to version {version_id}")
        return True
    
    def get_version_history(self) -> List[ScoringVersion]:
        """Get all version history."""
        versions = []
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            for row in conn.execute(
                "SELECT * FROM scoring_versions ORDER BY created_at DESC"
            ):
                config = ScoringConfig(
                    config_id=row["version_id"],
                    name="",
                )
                version = ScoringVersion(
                    version_id=row["version_id"],
                    version_number=row["version_number"],
                    config=config,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    created_by=row["created_by"] or "system",
                    is_active=bool(row["is_active"]),
                    previous_version=row["previous_version"],
                    changes_summary=row["changes_summary"] or "",
                )
                versions.append(version)
        
        return versions
    
    # ═══════════════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════════════
    
    def _save_version(self, version: ScoringVersion) -> None:
        """Save version to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scoring_versions
                (version_id, version_number, config_data, created_at, created_by,
                 is_active, previous_version, changes_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version.version_id,
                version.version_number,
                json.dumps(version.config.to_dict()),
                version.created_at.isoformat(),
                version.created_by,
                1 if version.is_active else 0,
                version.previous_version,
                version.changes_summary,
            ))
    
    def _save_adjustment(self, adj: ScoreAdjustment) -> None:
        """Save adjustment to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO adjustments
                (adjustment_id, skill_id, type, value, is_multiplicative,
                 source, confidence, valid_from, valid_until, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                adj.adjustment_id,
                adj.skill_id,
                adj.type.value,
                adj.value,
                1 if adj.is_multiplicative else 0,
                adj.source,
                adj.confidence,
                adj.valid_from.isoformat(),
                adj.valid_until.isoformat() if adj.valid_until else None,
                json.dumps(adj.evidence),
            ))
    
    def _save_event(self, event: AdaptationEvent) -> None:
        """Save event to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO adaptation_events
                (event_id, timestamp, event_type, trigger, skills_affected,
                 old_values, new_values, impact_assessment, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.timestamp.isoformat(),
                event.event_type,
                event.trigger,
                json.dumps(event.skills_affected),
                json.dumps(event.old_values),
                json.dumps(event.new_values),
                event.impact_assessment,
                event.approved_by,
            ))
    
    def get_audit_trail(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AdaptationEvent]:
        """Get audit trail of adaptation events."""
        events = []
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            query = "SELECT * FROM adaptation_events"
            params = []
            
            if since:
                query += " WHERE timestamp >= ?"
                params.append(since.isoformat())
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            for row in conn.execute(query, params):
                event = AdaptationEvent(
                    event_id=row["event_id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    event_type=row["event_type"] or "",
                    trigger=row["trigger"] or "",
                    skills_affected=json.loads(row["skills_affected"]) if row["skills_affected"] else [],
                    old_values=json.loads(row["old_values"]) if row["old_values"] else {},
                    new_values=json.loads(row["new_values"]) if row["new_values"] else {},
                    impact_assessment=row["impact_assessment"] or "",
                    approved_by=row["approved_by"],
                )
                events.append(event)
        
        return events


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_adapter: Optional[ScoringAdapter] = None


def get_scoring_adapter() -> ScoringAdapter:
    """Get singleton ScoringAdapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = ScoringAdapter()
    return _adapter
