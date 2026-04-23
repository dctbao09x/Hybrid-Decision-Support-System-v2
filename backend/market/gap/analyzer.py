# backend/market/gap/analyzer.py
"""
Career Gap Analyzer
===================

Gap analysis and learning path generation:
- User profile vs market demand matching
- Skill gap identification and prioritization
- Learning path optimization
- Career trajectory planning
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from .models import (
    CareerTarget,
    CareerTrajectory,
    GapAnalysisResult,
    GapSeverity,
    LearningPath,
    LearningResource,
    ResourceType,
    SkillGap,
    SkillLevel,
    UserProfile,
)

logger = logging.getLogger("market.gap.analyzer")


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

# Estimated months to improve one skill level
MONTHS_PER_LEVEL = {
    (SkillLevel.NONE, SkillLevel.BEGINNER): 1,
    (SkillLevel.BEGINNER, SkillLevel.INTERMEDIATE): 3,
    (SkillLevel.INTERMEDIATE, SkillLevel.ADVANCED): 6,
    (SkillLevel.ADVANCED, SkillLevel.EXPERT): 12,
}


def estimate_time_to_level(from_level: SkillLevel, to_level: SkillLevel) -> float:
    """Estimate months to improve from one level to another."""
    if from_level.value >= to_level.value:
        return 0
    
    total = 0
    current = from_level
    while current.value < to_level.value:
        next_level = SkillLevel(current.value + 1)
        key = (current, next_level)
        total += MONTHS_PER_LEVEL.get(key, 3)
        current = next_level
    
    return total


# ═══════════════════════════════════════════════════════════════════════
# Gap Analyzer
# ═══════════════════════════════════════════════════════════════════════


class GapAnalyzer:
    """
    Analyze skill gaps between user profiles and career targets.
    
    Features:
    - Comprehensive gap identification
    - Gap prioritization by market value
    - Strength identification
    - Readiness scoring
    - Learning path generation
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/gaps.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Skill market values (would be loaded from market data)
        self._skill_market_values: Dict[str, float] = {}
        
        # Learning resources catalog
        self._resources: List[LearningResource] = []
        
        # Career progression graph
        self._career_progressions: Dict[str, List[str]] = {}
        
        self._init_db()
        self._load_resources()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS gap_analyses (
                    analysis_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    target_career TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    overall_readiness REAL,
                    time_to_readiness REAL,
                    data TEXT  -- Full JSON
                );
                
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS career_targets (
                    career_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS learning_resources (
                    resource_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT,
                    provider TEXT,
                    data TEXT NOT NULL
                );
                
                CREATE INDEX IF NOT EXISTS idx_analyses_user ON gap_analyses(user_id);
            """)
    
    def _load_resources(self) -> None:
        """Load learning resources from database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            for row in conn.execute("SELECT * FROM learning_resources"):
                data = json.loads(row["data"])
                resource = LearningResource(
                    resource_id=row["resource_id"],
                    title=row["title"],
                    type=ResourceType(data.get("type", "course")),
                    provider=data.get("provider", ""),
                    url=data.get("url", ""),
                    duration_hours=data.get("duration_hours", 0),
                    cost=data.get("cost", 0),
                    skill_coverage=data.get("skill_coverage", {}),
                    rating=data.get("rating", 0),
                    difficulty=SkillLevel(data.get("difficulty", 1)),
                    prerequisites=data.get("prerequisites", []),
                )
                self._resources.append(resource)
    
    def analyze_gap(
        self,
        user: UserProfile,
        target: CareerTarget,
    ) -> GapAnalysisResult:
        """
        Perform comprehensive gap analysis.
        
        Args:
            user: User's current profile
            target: Target career
        
        Returns:
            GapAnalysisResult with gaps, strengths, and recommendations
        """
        analysis_id = f"gap_{user.user_id}_{target.career_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        # Identify skill gaps
        skill_gaps = self._identify_gaps(user, target)
        
        # Identify strengths
        strengths = self._identify_strengths(user, target)
        
        # Calculate overall readiness
        readiness = self._calculate_readiness(user, target, skill_gaps)
        
        # Estimate time to readiness
        time_to_ready = self._estimate_time_to_readiness(skill_gaps)
        
        # Generate learning paths
        paths = self._generate_learning_paths(user, target, skill_gaps)
        
        # Find alternative targets
        alternatives = self._find_alternative_targets(user, target)
        
        # Generate summary
        summary = self._generate_summary(user, target, readiness, skill_gaps)
        
        result = GapAnalysisResult(
            analysis_id=analysis_id,
            user_id=user.user_id,
            target=target,
            overall_readiness=readiness,
            skill_gaps=skill_gaps,
            strengths=strengths,
            recommended_paths=paths,
            time_to_readiness=time_to_ready,
            alternative_targets=alternatives,
            summary=summary,
        )
        
        # Save analysis
        self._save_analysis(result)
        
        return result
    
    def _identify_gaps(
        self,
        user: UserProfile,
        target: CareerTarget,
    ) -> List[SkillGap]:
        """Identify all skill gaps."""
        gaps = []
        
        # Check required skills
        for skill_id, required_level in target.required_skills.items():
            current_level = user.skills.get(skill_id, SkillLevel.NONE)
            
            if current_level.value < required_level.value:
                gap_size = required_level.value - current_level.value
                market_value = self._skill_market_values.get(skill_id, 50.0)
                time_to_close = estimate_time_to_level(current_level, required_level)
                
                # Determine severity
                if current_level == SkillLevel.NONE and gap_size >= 2:
                    severity = GapSeverity.CRITICAL
                elif gap_size >= 2:
                    severity = GapSeverity.HIGH
                else:
                    severity = GapSeverity.MEDIUM
                
                # Priority score: severity * market_value / time
                time_factor = max(1, time_to_close)
                priority = (4 - ["critical", "high", "medium", "low"].index(severity.value)) * market_value / time_factor
                
                gaps.append(SkillGap(
                    skill_id=skill_id,
                    skill_name=skill_id,  # Would resolve from taxonomy
                    current_level=current_level,
                    required_level=required_level,
                    gap_size=gap_size,
                    severity=severity,
                    market_value=market_value,
                    time_to_close=time_to_close,
                    priority_score=priority,
                ))
        
        # Check preferred skills
        for skill_id, preferred_level in target.preferred_skills.items():
            if skill_id in target.required_skills:
                continue  # Already covered
            
            current_level = user.skills.get(skill_id, SkillLevel.NONE)
            
            if current_level.value < preferred_level.value:
                gap_size = preferred_level.value - current_level.value
                market_value = self._skill_market_values.get(skill_id, 30.0)
                time_to_close = estimate_time_to_level(current_level, preferred_level)
                
                severity = GapSeverity.LOW if gap_size == 1 else GapSeverity.MEDIUM
                time_factor = max(1, time_to_close)
                priority = (4 - ["critical", "high", "medium", "low"].index(severity.value)) * market_value / time_factor * 0.7
                
                gaps.append(SkillGap(
                    skill_id=skill_id,
                    skill_name=skill_id,
                    current_level=current_level,
                    required_level=preferred_level,
                    gap_size=gap_size,
                    severity=severity,
                    market_value=market_value,
                    time_to_close=time_to_close,
                    priority_score=priority,
                ))
        
        # Sort by priority
        gaps.sort(key=lambda g: -g.priority_score)
        
        return gaps
    
    def _identify_strengths(
        self,
        user: UserProfile,
        target: CareerTarget,
    ) -> List[str]:
        """Identify user's strengths relative to target."""
        strengths = []
        
        # Skills exceeding requirements
        for skill_id, required_level in target.required_skills.items():
            current_level = user.skills.get(skill_id, SkillLevel.NONE)
            if current_level.value >= required_level.value:
                if current_level.value > required_level.value:
                    strengths.append(f"Exceeds {skill_id} requirement ({current_level.name} vs {required_level.name} required)")
                else:
                    strengths.append(f"Meets {skill_id} requirement")
        
        # Experience advantage
        if user.experience_years >= target.min_experience * 1.2:
            strengths.append(f"Strong experience ({user.experience_years:.1f} years)")
        
        # Relevant certifications
        relevant_certs = [c for c in user.certifications if any(
            skill in c.lower() for skill in target.required_skills
        )]
        if relevant_certs:
            strengths.append(f"Relevant certifications: {', '.join(relevant_certs)}")
        
        return strengths
    
    def _calculate_readiness(
        self,
        user: UserProfile,
        target: CareerTarget,
        gaps: List[SkillGap],
    ) -> float:
        """Calculate overall readiness score (0-100)."""
        if not target.required_skills:
            return 100.0
        
        # Skill readiness
        total_required = len(target.required_skills)
        skills_met = sum(
            1 for skill_id in target.required_skills
            if user.skills.get(skill_id, SkillLevel.NONE).value >= target.required_skills[skill_id].value
        )
        skill_readiness = skills_met / total_required * 100 if total_required > 0 else 100
        
        # Experience readiness
        exp_readiness = min(100, user.experience_years / target.min_experience * 100) if target.min_experience > 0 else 100
        
        # Weighted combination
        overall = skill_readiness * 0.7 + exp_readiness * 0.3
        
        # Penalty for critical gaps
        critical_gaps = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL)
        if critical_gaps > 0:
            overall *= (1 - 0.1 * critical_gaps)
        
        return max(0, min(100, overall))
    
    def _estimate_time_to_readiness(self, gaps: List[SkillGap]) -> float:
        """Estimate total months to close all critical/high gaps."""
        # Can work on multiple skills in parallel but with reduced efficiency
        critical_high = [g for g in gaps if g.severity in [GapSeverity.CRITICAL, GapSeverity.HIGH]]
        
        if not critical_high:
            return 0
        
        # Estimate parallel learning: can work on 2-3 skills simultaneously
        total_time = sum(g.time_to_close for g in critical_high)
        parallel_factor = 2.5
        
        return total_time / parallel_factor
    
    def _generate_learning_paths(
        self,
        user: UserProfile,
        target: CareerTarget,
        gaps: List[SkillGap],
    ) -> List[LearningPath]:
        """Generate recommended learning paths."""
        if not gaps:
            return []
        
        paths = []
        
        # Fast track path - focus on critical gaps
        critical_gaps = [g for g in gaps if g.severity in [GapSeverity.CRITICAL, GapSeverity.HIGH]]
        if critical_gaps:
            fast_path = self._create_path(
                f"fast_track_{target.career_id}",
                f"Fast Track to {target.title}",
                target.title,
                critical_gaps,
                user.constraints,
            )
            paths.append(fast_path)
        
        # Comprehensive path - all gaps
        comprehensive_path = self._create_path(
            f"comprehensive_{target.career_id}",
            f"Comprehensive Path to {target.title}",
            target.title,
            gaps,
            user.constraints,
        )
        paths.append(comprehensive_path)
        
        # Budget-friendly path
        if user.constraints.get("budget_limit"):
            budget_path = self._create_budget_path(
                f"budget_{target.career_id}",
                f"Budget Path to {target.title}",
                target.title,
                gaps,
                user.constraints.get("budget_limit", 500),
            )
            paths.append(budget_path)
        
        return paths
    
    def _create_path(
        self,
        path_id: str,
        name: str,
        target_career: str,
        gaps: List[SkillGap],
        constraints: Dict[str, Any],
    ) -> LearningPath:
        """Create a learning path for given gaps."""
        resources = []
        total_duration = 0
        total_cost = 0
        milestones = []
        skill_progression = []
        
        # Find resources for each gap
        for gap in gaps:
            matching_resources = self._find_resources_for_skill(gap.skill_id, gap.gap_size)
            
            for resource in matching_resources[:2]:  # Max 2 resources per skill
                resources.append(resource)
                total_duration += resource.duration_hours / 40  # Convert to months (40h/month study)
                total_cost += resource.cost
        
        # Create milestones
        current_month = 0
        for i, gap in enumerate(gaps[:5]):  # Top 5 gaps as milestones
            milestone_month = current_month + gap.time_to_close
            milestones.append({
                "month": milestone_month,
                "skill": gap.skill_name,
                "level": gap.required_level.name,
                "description": f"Achieve {gap.required_level.name} in {gap.skill_name}",
            })
            
            skill_progression.append({
                "month": milestone_month,
                "skill": gap.skill_name,
                "from_level": gap.current_level.value,
                "to_level": gap.required_level.value,
            })
            
            current_month = milestone_month
        
        # Completion confidence based on gap severity
        if gaps:
            critical_count = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL)
            confidence = max(0.5, 1.0 - 0.1 * critical_count)
        else:
            confidence = 1.0
        
        return LearningPath(
            path_id=path_id,
            name=name,
            target_career=target_career,
            total_duration=total_duration,
            total_cost=total_cost,
            milestones=milestones,
            resources=resources,
            skill_progression=skill_progression,
            completion_confidence=confidence,
        )
    
    def _create_budget_path(
        self,
        path_id: str,
        name: str,
        target_career: str,
        gaps: List[SkillGap],
        budget: float,
    ) -> LearningPath:
        """Create a budget-constrained learning path."""
        resources = []
        total_cost = 0
        
        # Sort gaps by priority/cost ratio
        for gap in sorted(gaps, key=lambda g: -g.priority_score):
            matching = self._find_resources_for_skill(gap.skill_id, gap.gap_size)
            
            # Find cheapest option
            cheap_resources = sorted(matching, key=lambda r: r.cost)
            
            for resource in cheap_resources:
                if total_cost + resource.cost <= budget:
                    resources.append(resource)
                    total_cost += resource.cost
                    break
        
        total_duration = sum(r.duration_hours / 40 for r in resources)
        
        return LearningPath(
            path_id=path_id,
            name=name,
            target_career=target_career,
            total_duration=total_duration,
            total_cost=total_cost,
            resources=resources,
            completion_confidence=0.6,  # Lower confidence due to constraints
        )
    
    def _find_resources_for_skill(
        self,
        skill_id: str,
        levels_needed: int,
    ) -> List[LearningResource]:
        """Find learning resources that cover a skill."""
        matching = [
            r for r in self._resources
            if skill_id in r.skill_coverage and r.skill_coverage[skill_id] >= levels_needed
        ]
        
        if not matching:
            # Return generic placeholder
            return [LearningResource(
                resource_id=f"gen_{skill_id}",
                title=f"Learn {skill_id}",
                type=ResourceType.COURSE,
                provider="Various",
                duration_hours=levels_needed * 40,
                cost=levels_needed * 50,
                skill_coverage={skill_id: levels_needed},
            )]
        
        return sorted(matching, key=lambda r: -r.rating)
    
    def _find_alternative_targets(
        self,
        user: UserProfile,
        original_target: CareerTarget,
    ) -> List[str]:
        """Find alternative careers user might be better suited for."""
        # Would query career database and find matches
        # For now, return placeholders based on skills
        alternatives = []
        
        user_skills = set(user.skills.keys())
        
        # Find careers sharing skillsets
        for career_id, progression in self._career_progressions.items():
            if career_id == original_target.career_id:
                continue
            # Would check skill overlap here
        
        return alternatives[:3]
    
    def _generate_summary(
        self,
        user: UserProfile,
        target: CareerTarget,
        readiness: float,
        gaps: List[SkillGap],
    ) -> str:
        """Generate human-readable analysis summary."""
        parts = []
        
        # Readiness level
        if readiness >= 80:
            parts.append(f"Strong readiness ({readiness:.0f}%) for {target.title}")
        elif readiness >= 50:
            parts.append(f"Moderate readiness ({readiness:.0f}%) for {target.title}")
        else:
            parts.append(f"Significant preparation needed ({readiness:.0f}% ready) for {target.title}")
        
        # Critical gaps
        critical = [g for g in gaps if g.severity == GapSeverity.CRITICAL]
        if critical:
            skills = ", ".join(g.skill_name for g in critical[:3])
            parts.append(f"Critical gaps: {skills}")
        
        # Time estimate
        total_time = sum(g.time_to_close for g in gaps if g.severity in [GapSeverity.CRITICAL, GapSeverity.HIGH])
        if total_time > 0:
            parts.append(f"Estimated preparation time: {total_time / 2:.0f} months (with focused study)")
        
        return ". ".join(parts)
    
    def _save_analysis(self, result: GapAnalysisResult) -> None:
        """Save analysis to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO gap_analyses
                (analysis_id, user_id, target_career, timestamp, 
                 overall_readiness, time_to_readiness, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                result.analysis_id,
                result.user_id,
                result.target.career_id,
                result.timestamp.isoformat(),
                result.overall_readiness,
                result.time_to_readiness,
                json.dumps(result.to_dict()),
            ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Trajectory Planning
    # ═══════════════════════════════════════════════════════════════════
    
    def plan_trajectory(
        self,
        user: UserProfile,
        final_target: str,
        max_years: int = 10,
    ) -> CareerTrajectory:
        """
        Plan long-term career trajectory.
        
        Args:
            user: Current user profile
            final_target: Ultimate career goal
            max_years: Maximum planning horizon
        
        Returns:
            CareerTrajectory with milestones and progression
        """
        trajectory_id = f"traj_{user.user_id}_{final_target}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        
        milestones = []
        current_role = user.current_role
        
        # Find progression path
        progression = self._career_progressions.get(final_target, [])
        
        years_elapsed = 0
        for next_role in progression:
            # Estimate years to reach next milestone
            years_to_next = 2  # Would calculate based on gap analysis
            years_elapsed += years_to_next
            
            if years_elapsed > max_years:
                break
            
            milestones.append((next_role, years_elapsed))
            current_role = next_role
        
        # Final target
        if years_elapsed <= max_years:
            milestones.append((final_target, years_elapsed + 2))
        
        # Key skills needed
        key_skills = list(set().union(
            *[self._career_progressions.get(m[0], []) for m in milestones]
        ))[:10]
        
        return CareerTrajectory(
            trajectory_id=trajectory_id,
            user_id=user.user_id,
            current_role=user.current_role,
            milestones=milestones,
            final_target=final_target,
            total_years=milestones[-1][1] if milestones else 0,
            key_skills_needed=key_skills,
            risk_factors=[
                "Market conditions may change",
                "Skill requirements evolving",
            ],
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Market Value Integration
    # ═══════════════════════════════════════════════════════════════════
    
    def update_skill_market_values(self, values: Dict[str, float]) -> None:
        """Update skill market values from trend analysis."""
        self._skill_market_values.update(values)
    
    def register_learning_resource(self, resource: LearningResource) -> None:
        """Register a new learning resource."""
        self._resources.append(resource)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO learning_resources
                (resource_id, title, type, provider, data)
                VALUES (?, ?, ?, ?, ?)
            """, (
                resource.resource_id,
                resource.title,
                resource.type.value,
                resource.provider,
                json.dumps(resource.to_dict()),
            ))


# ═══════════════════════════════════════════════════════════════════════
# Path Optimizer
# ═══════════════════════════════════════════════════════════════════════


class PathOptimizer:
    """
    Optimize learning paths using constraint satisfaction.
    
    Considers:
    - Time constraints
    - Budget constraints
    - Learning dependencies
    - Skill priorities
    """
    
    def __init__(self):
        self._resource_graph: Dict[str, List[str]] = {}  # Prerequisites
    
    def optimize_path(
        self,
        gaps: List[SkillGap],
        resources: List[LearningResource],
        constraints: Dict[str, Any],
    ) -> List[LearningResource]:
        """
        Find optimal resource sequence.
        
        Args:
            gaps: Skill gaps to address
            resources: Available resources
            constraints: Time, budget, etc.
        
        Returns:
            Ordered list of resources
        """
        max_time = constraints.get("max_months", 12) * 40  # Convert to hours
        max_cost = constraints.get("budget_limit", float("inf"))
        
        # Build skill coverage mapping
        skill_resources = defaultdict(list)
        for resource in resources:
            for skill in resource.skill_coverage:
                skill_resources[skill].append(resource)
        
        # Greedy selection based on priority * coverage / cost
        selected = []
        remaining_gaps = set(g.skill_id for g in gaps)
        total_time = 0
        total_cost = 0
        
        while remaining_gaps:
            best_resource = None
            best_score = -1
            
            for skill_id in remaining_gaps:
                for resource in skill_resources.get(skill_id, []):
                    if resource in selected:
                        continue
                    
                    # Check constraints
                    if total_time + resource.duration_hours > max_time:
                        continue
                    if total_cost + resource.cost > max_cost:
                        continue
                    
                    # Check prerequisites
                    prereqs_met = all(
                        p in [r.resource_id for r in selected]
                        for p in resource.prerequisites
                    )
                    if not prereqs_met:
                        continue
                    
                    # Calculate score
                    gap = next((g for g in gaps if g.skill_id == skill_id), None)
                    if gap:
                        priority = gap.priority_score
                        coverage = len([s for s in resource.skill_coverage if s in remaining_gaps])
                        cost_factor = max(1, resource.cost)
                        score = priority * coverage / cost_factor * 100
                        
                        if score > best_score:
                            best_score = score
                            best_resource = resource
            
            if best_resource:
                selected.append(best_resource)
                total_time += best_resource.duration_hours
                total_cost += best_resource.cost
                
                # Mark covered gaps
                for skill in best_resource.skill_coverage:
                    remaining_gaps.discard(skill)
            else:
                break  # No more resources can be added
        
        return selected


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_analyzer: Optional[GapAnalyzer] = None


def get_gap_analyzer() -> GapAnalyzer:
    """Get singleton GapAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = GapAnalyzer()
    return _analyzer
