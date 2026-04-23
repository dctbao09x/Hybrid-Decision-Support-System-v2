# backend/market/trends/detector.py
"""
Skill Trend & Drift Detector
============================

Time-series analysis for skill market trends:
- Frequency velocity calculation
- Salary correlation analysis
- Co-skill emergence detection
- Change point detection
- Drift monitoring
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from .models import (
    ChangePoint,
    CoSkillPair,
    SkillDrift,
    SkillTrend,
    TrendDirection,
    TrendSignal,
    TrendSnapshot,
    IndustryTrend,
    GeographicTrend,
)

logger = logging.getLogger("market.trends.detector")


# ═══════════════════════════════════════════════════════════════════════
# Time Series Utilities
# ═══════════════════════════════════════════════════════════════════════


def compute_velocity(time_series: List[Tuple[datetime, float]]) -> float:
    """
    Compute velocity (rate of change) from time series.
    
    Returns monthly percentage change.
    """
    if len(time_series) < 2:
        return 0.0
    
    # Sort by time
    sorted_ts = sorted(time_series, key=lambda x: x[0])
    
    # Use linear regression for velocity
    times = [(ts[0] - sorted_ts[0][0]).days for ts in sorted_ts]
    values = [ts[1] for ts in sorted_ts]
    
    if max(times) == 0:
        return 0.0
    
    # Simple linear regression
    n = len(times)
    sum_x = sum(times)
    sum_y = sum(values)
    sum_xy = sum(t * v for t, v in zip(times, values))
    sum_xx = sum(t * t for t in times)
    
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0
    
    slope = (n * sum_xy - sum_x * sum_y) / denom
    
    # Convert to monthly percentage
    mean_value = sum_y / n if n > 0 else 1
    if mean_value == 0:
        return 0.0
    
    monthly_change = slope * 30 / mean_value * 100
    return monthly_change


def detect_change_points(
    time_series: List[Tuple[datetime, float]],
    min_segment_size: int = 3,
    threshold: float = 2.0,
) -> List[Tuple[datetime, float]]:
    """
    Detect change points in time series using CUSUM-like algorithm.
    
    Returns list of (timestamp, change_magnitude) tuples.
    """
    if len(time_series) < min_segment_size * 2:
        return []
    
    sorted_ts = sorted(time_series, key=lambda x: x[0])
    values = [ts[1] for ts in sorted_ts]
    
    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) if len(values) > 1 else 1
    
    if std == 0:
        return []
    
    # Cumulative sum of deviations
    cusum_pos = 0
    cusum_neg = 0
    change_points = []
    
    for i, (ts, val) in enumerate(sorted_ts):
        deviation = (val - mean) / std
        cusum_pos = max(0, cusum_pos + deviation - 0.5)
        cusum_neg = min(0, cusum_neg + deviation + 0.5)
        
        if cusum_pos > threshold:
            change_points.append((ts, cusum_pos))
            cusum_pos = 0
        elif cusum_neg < -threshold:
            change_points.append((ts, cusum_neg))
            cusum_neg = 0
    
    return change_points


def moving_average(
    time_series: List[Tuple[datetime, float]],
    window_days: int = 7,
) -> List[Tuple[datetime, float]]:
    """Compute moving average of time series."""
    if not time_series:
        return []
    
    sorted_ts = sorted(time_series, key=lambda x: x[0])
    result = []
    
    for i, (ts, _) in enumerate(sorted_ts):
        window_start = ts - timedelta(days=window_days)
        window_values = [
            v for t, v in sorted_ts[:i + 1]
            if t >= window_start
        ]
        if window_values:
            result.append((ts, sum(window_values) / len(window_values)))
    
    return result


# ═══════════════════════════════════════════════════════════════════════
# Trend Detector
# ═══════════════════════════════════════════════════════════════════════


class TrendDetector:
    """
    Detect and analyze skill market trends.
    
    Features:
    - Frequency velocity calculation
    - Salary correlation analysis
    - Co-skill emergence detection
    - Change point detection
    - Industry/geographic trend analysis
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/trends.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Trend thresholds
        self._rapidly_growing_threshold = 20.0  # > +20% MoM
        self._growing_threshold = 5.0           # > +5% MoM
        self._declining_threshold = -5.0        # < -5% MoM
        self._rapidly_declining_threshold = -20.0  # < -20% MoM
        
        # Co-occurrence thresholds
        self._min_lift = 1.5                    # Minimum lift for significant correlation
        self._min_co_occurrence = 0.05          # Minimum co-occurrence rate
        
        # Callbacks
        self._on_trend_detected: List[Callable[[SkillTrend], None]] = []
        self._on_change_point: List[Callable[[ChangePoint], None]] = []
        self._on_drift_detected: List[Callable[[SkillDrift], None]] = []
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS skill_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    salary REAL,
                    job_id TEXT,
                    industry TEXT,
                    region TEXT,
                    experience_level TEXT
                );
                
                CREATE TABLE IF NOT EXISTS co_occurrences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_a TEXT NOT NULL,
                    skill_b TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    job_id TEXT,
                    industry TEXT,
                    region TEXT
                );
                
                CREATE TABLE IF NOT EXISTS trend_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    period_days INTEGER,
                    data TEXT  -- JSON
                );
                
                CREATE TABLE IF NOT EXISTS change_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    value_before REAL,
                    value_after REAL,
                    magnitude REAL,
                    confidence REAL
                );
                
                CREATE TABLE IF NOT EXISTS drift_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    drift_type TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    magnitude REAL,
                    evidence TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_obs_skill ON skill_observations(skill_id);
                CREATE INDEX IF NOT EXISTS idx_obs_time ON skill_observations(timestamp);
                CREATE INDEX IF NOT EXISTS idx_cooc_skills ON co_occurrences(skill_a, skill_b);
            """)
    
    # ═══════════════════════════════════════════════════════════════════
    # Data Collection
    # ═══════════════════════════════════════════════════════════════════
    
    def record_skill_observation(
        self,
        skill_id: str,
        salary: Optional[float] = None,
        job_id: Optional[str] = None,
        industry: Optional[str] = None,
        region: Optional[str] = None,
        experience_level: Optional[str] = None,
    ) -> None:
        """Record a skill observation from market data."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO skill_observations
                (skill_id, timestamp, salary, job_id, industry, region, experience_level)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                skill_id,
                datetime.now(timezone.utc).isoformat(),
                salary,
                job_id,
                industry,
                region,
                experience_level,
            ))
    
    def record_co_occurrence(
        self,
        skills: List[str],
        job_id: Optional[str] = None,
        industry: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        """Record co-occurrence of skills in a job posting."""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            # Record all pairs
            for i, skill_a in enumerate(skills):
                for skill_b in skills[i + 1:]:
                    # Ensure consistent ordering
                    if skill_a > skill_b:
                        skill_a, skill_b = skill_b, skill_a
                    
                    conn.execute("""
                        INSERT INTO co_occurrences
                        (skill_a, skill_b, timestamp, job_id, industry, region)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (skill_a, skill_b, timestamp, job_id, industry, region))
    
    # ═══════════════════════════════════════════════════════════════════
    # Trend Analysis
    # ═══════════════════════════════════════════════════════════════════
    
    def analyze_skill_trend(
        self,
        skill_id: str,
        period_days: int = 90,
    ) -> SkillTrend:
        """Analyze trend for a single skill."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get frequency time series
            freq_rows = conn.execute("""
                SELECT DATE(timestamp) as date, COUNT(*) as cnt
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ?
                GROUP BY DATE(timestamp)
                ORDER BY date
            """, (skill_id, cutoff.isoformat())).fetchall()
            
            frequency_ts = [
                (datetime.fromisoformat(row["date"]), row["cnt"])
                for row in freq_rows
            ]
            
            # Get salary time series
            salary_rows = conn.execute("""
                SELECT DATE(timestamp) as date, AVG(salary) as avg_sal
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ? AND salary IS NOT NULL
                GROUP BY DATE(timestamp)
                ORDER BY date
            """, (skill_id, cutoff.isoformat())).fetchall()
            
            salary_ts = [
                (datetime.fromisoformat(row["date"]), row["avg_sal"])
                for row in salary_rows
                if row["avg_sal"]
            ]
        
        # Calculate velocities
        freq_velocity = compute_velocity(frequency_ts)
        salary_velocity = compute_velocity(salary_ts)
        
        # Determine direction
        direction = self._classify_direction(freq_velocity)
        
        # Detect signals
        signals = self._detect_signals(
            skill_id,
            frequency_ts,
            salary_ts,
            freq_velocity,
            salary_velocity,
        )
        
        # Calculate confidence
        confidence = self._calculate_trend_confidence(frequency_ts)
        
        trend = SkillTrend(
            skill_id=skill_id,
            skill_name=skill_id,  # Would be resolved from taxonomy
            period_start=cutoff,
            period_end=datetime.now(timezone.utc),
            direction=direction,
            frequency_velocity=freq_velocity,
            salary_velocity=salary_velocity,
            frequency_time_series=frequency_ts,
            salary_time_series=salary_ts,
            confidence=confidence,
            signals=signals,
        )
        
        # Trigger callbacks
        for callback in self._on_trend_detected:
            try:
                callback(trend)
            except Exception as e:
                logger.error(f"Trend callback error: {e}")
        
        return trend
    
    def _classify_direction(self, velocity: float) -> TrendDirection:
        """Classify trend direction based on velocity."""
        if velocity >= self._rapidly_growing_threshold:
            return TrendDirection.RAPIDLY_GROWING
        elif velocity >= self._growing_threshold:
            return TrendDirection.GROWING
        elif velocity <= self._rapidly_declining_threshold:
            return TrendDirection.RAPIDLY_DECLINING
        elif velocity <= self._declining_threshold:
            return TrendDirection.DECLINING
        else:
            return TrendDirection.STABLE
    
    def _detect_signals(
        self,
        skill_id: str,
        frequency_ts: List[Tuple[datetime, float]],
        salary_ts: List[Tuple[datetime, float]],
        freq_velocity: float,
        salary_velocity: float,
    ) -> List[TrendSignal]:
        """Detect notable trend signals."""
        signals = []
        
        # Frequency signals
        if freq_velocity > 30:
            signals.append(TrendSignal.FREQUENCY_SPIKE)
        elif freq_velocity < -30:
            signals.append(TrendSignal.FREQUENCY_DROP)
        
        # Salary signals
        if salary_velocity > 15:
            signals.append(TrendSignal.SALARY_SURGE)
        elif salary_velocity < -15:
            signals.append(TrendSignal.SALARY_DROP)
        
        return signals
    
    def _calculate_trend_confidence(
        self,
        time_series: List[Tuple[datetime, float]],
    ) -> float:
        """Calculate confidence based on data quality."""
        if not time_series:
            return 0.0
        
        # More data points = higher confidence
        n_points = len(time_series)
        data_confidence = min(1.0, n_points / 30)  # Max confidence at 30+ points
        
        # Consistent trend = higher confidence
        if n_points < 3:
            return data_confidence * 0.5
        
        # Check for trend consistency
        values = [ts[1] for ts in sorted(time_series, key=lambda x: x[0])]
        increases = sum(1 for i in range(1, len(values)) if values[i] > values[i-1])
        decreases = sum(1 for i in range(1, len(values)) if values[i] < values[i-1])
        
        consistency = max(increases, decreases) / (len(values) - 1) if len(values) > 1 else 0
        
        return data_confidence * (0.5 + 0.5 * consistency)
    
    # ═══════════════════════════════════════════════════════════════════
    # Co-Skill Analysis
    # ═══════════════════════════════════════════════════════════════════
    
    def analyze_co_skills(
        self,
        period_days: int = 90,
        min_occurrences: int = 5,
    ) -> List[CoSkillPair]:
        """Analyze skill co-occurrence patterns."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get individual skill frequencies
            skill_freq = {}
            for row in conn.execute("""
                SELECT skill_id, COUNT(*) as cnt
                FROM skill_observations
                WHERE timestamp >= ?
                GROUP BY skill_id
            """, (cutoff.isoformat(),)):
                skill_freq[row["skill_id"]] = row["cnt"]
            
            total_jobs = conn.execute("""
                SELECT COUNT(DISTINCT job_id) FROM skill_observations
                WHERE timestamp >= ? AND job_id IS NOT NULL
            """, (cutoff.isoformat(),)).fetchone()[0] or 1
            
            # Get co-occurrence counts
            pairs = []
            for row in conn.execute("""
                SELECT skill_a, skill_b, COUNT(*) as cnt,
                       MIN(timestamp) as first_seen
                FROM co_occurrences
                WHERE timestamp >= ?
                GROUP BY skill_a, skill_b
                HAVING cnt >= ?
            """, (cutoff.isoformat(), min_occurrences)):
                skill_a = row["skill_a"]
                skill_b = row["skill_b"]
                co_count = row["cnt"]
                
                # Calculate metrics
                freq_a = skill_freq.get(skill_a, 1)
                freq_b = skill_freq.get(skill_b, 1)
                
                p_a = freq_a / total_jobs
                p_b = freq_b / total_jobs
                p_ab = co_count / total_jobs
                
                expected = p_a * p_b
                lift = p_ab / expected if expected > 0 else 1.0
                co_occurrence_rate = p_ab
                
                if lift >= self._min_lift and co_occurrence_rate >= self._min_co_occurrence:
                    pairs.append(CoSkillPair(
                        skill_a=skill_a,
                        skill_b=skill_b,
                        co_occurrence_rate=co_occurrence_rate,
                        lift=lift,
                        first_observed=datetime.fromisoformat(row["first_seen"]),
                    ))
        
        # Sort by lift
        pairs.sort(key=lambda p: -p.lift)
        
        return pairs
    
    def detect_emerging_correlations(
        self,
        lookback_days: int = 30,
        baseline_days: int = 90,
    ) -> List[CoSkillPair]:
        """
        Detect newly emerging skill correlations.
        
        Compares recent period to baseline to find new relationships.
        """
        recent_pairs = {
            (p.skill_a, p.skill_b): p
            for p in self.analyze_co_skills(lookback_days)
        }
        
        # Get baseline pairs from before lookback
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        baseline_cutoff = cutoff - timedelta(days=baseline_days)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            baseline_pairs = set()
            for row in conn.execute("""
                SELECT skill_a, skill_b
                FROM co_occurrences
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY skill_a, skill_b
                HAVING COUNT(*) >= 5
            """, (baseline_cutoff.isoformat(), cutoff.isoformat())):
                baseline_pairs.add((row["skill_a"], row["skill_b"]))
        
        # Find new correlations
        emerging = []
        for key, pair in recent_pairs.items():
            if key not in baseline_pairs:
                pair.signals = [TrendSignal.NEW_CORRELATION]
                emerging.append(pair)
        
        return emerging
    
    # ═══════════════════════════════════════════════════════════════════
    # Change Point Detection
    # ═══════════════════════════════════════════════════════════════════
    
    def detect_change_points_for_skill(
        self,
        skill_id: str,
        period_days: int = 180,
    ) -> List[ChangePoint]:
        """Detect change points in skill metrics."""
        trend = self.analyze_skill_trend(skill_id, period_days)
        change_points = []
        
        # Frequency change points
        freq_changes = detect_change_points(trend.frequency_time_series)
        for ts, magnitude in freq_changes:
            # Calculate before/after values
            before = [v for t, v in trend.frequency_time_series if t < ts]
            after = [v for t, v in trend.frequency_time_series if t >= ts]
            
            cp = ChangePoint(
                skill_id=skill_id,
                metric="frequency",
                timestamp=ts,
                value_before=sum(before) / len(before) if before else 0,
                value_after=sum(after) / len(after) if after else 0,
                change_magnitude=magnitude,
                confidence=0.8,
            )
            change_points.append(cp)
            
            # Save and trigger callback
            self._save_change_point(cp)
            for callback in self._on_change_point:
                try:
                    callback(cp)
                except Exception as e:
                    logger.error(f"Change point callback error: {e}")
        
        # Salary change points
        salary_changes = detect_change_points(trend.salary_time_series)
        for ts, magnitude in salary_changes:
            before = [v for t, v in trend.salary_time_series if t < ts]
            after = [v for t, v in trend.salary_time_series if t >= ts]
            
            cp = ChangePoint(
                skill_id=skill_id,
                metric="salary",
                timestamp=ts,
                value_before=sum(before) / len(before) if before else 0,
                value_after=sum(after) / len(after) if after else 0,
                change_magnitude=magnitude,
                confidence=0.8,
            )
            change_points.append(cp)
            self._save_change_point(cp)
        
        return change_points
    
    def _save_change_point(self, cp: ChangePoint) -> None:
        """Save change point to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO change_points
                (skill_id, metric, timestamp, value_before, value_after, magnitude, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                cp.skill_id,
                cp.metric,
                cp.timestamp.isoformat(),
                cp.value_before,
                cp.value_after,
                cp.change_magnitude,
                cp.confidence,
            ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Snapshot Generation
    # ═══════════════════════════════════════════════════════════════════
    
    def create_snapshot(
        self,
        skill_ids: List[str],
        period_days: int = 90,
    ) -> TrendSnapshot:
        """Create comprehensive trend snapshot."""
        snapshot_id = f"snap_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        rapid_growing = []
        growing = []
        stable = []
        declining = []
        rapid_declining = []
        
        for skill_id in skill_ids:
            trend = self.analyze_skill_trend(skill_id, period_days)
            
            if trend.direction == TrendDirection.RAPIDLY_GROWING:
                rapid_growing.append(trend)
            elif trend.direction == TrendDirection.GROWING:
                growing.append(trend)
            elif trend.direction == TrendDirection.DECLINING:
                declining.append(trend)
            elif trend.direction == TrendDirection.RAPIDLY_DECLINING:
                rapid_declining.append(trend)
            else:
                stable.append(trend)
        
        emerging = self.detect_emerging_correlations()
        
        # Generate summary
        summary_parts = []
        if rapid_growing:
            summary_parts.append(f"{len(rapid_growing)} skills rapidly growing")
        if rapid_declining:
            summary_parts.append(f"{len(rapid_declining)} skills rapidly declining")
        if emerging:
            summary_parts.append(f"{len(emerging)} new skill correlations")
        
        snapshot = TrendSnapshot(
            snapshot_id=snapshot_id,
            period_days=period_days,
            total_skills_analyzed=len(skill_ids),
            rapidly_growing=rapid_growing,
            growing=growing,
            stable=stable,
            declining=declining,
            rapidly_declining=rapid_declining,
            emerging_correlations=emerging,
            summary="; ".join(summary_parts) or "Market stable",
        )
        
        # Save snapshot
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO trend_snapshots (snapshot_id, timestamp, period_days, data)
                VALUES (?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                snapshot.timestamp.isoformat(),
                snapshot.period_days,
                json.dumps(snapshot.to_dict()),
            ))
        
        return snapshot


# ═══════════════════════════════════════════════════════════════════════
# Drift Analyzer
# ═══════════════════════════════════════════════════════════════════════


class DriftAnalyzer:
    """
    Detect drift in skill requirements and characteristics.
    
    Monitors for:
    - Experience level shifts
    - Industry migration
    - Geographic expansion/contraction
    - Salary level changes
    - Tool/technology substitution
    """
    
    def __init__(self, trend_detector: TrendDetector):
        self._detector = trend_detector
        self._db_path = trend_detector._db_path
        
        # Drift thresholds
        self._experience_drift_threshold = 0.2  # 20% shift in experience distribution
        self._industry_drift_threshold = 0.3    # 30% shift in industry distribution
        self._salary_drift_threshold = 0.15     # 15% salary change
    
    def detect_experience_drift(
        self,
        skill_id: str,
        baseline_days: int = 90,
        recent_days: int = 30,
    ) -> Optional[SkillDrift]:
        """Detect drift in experience level requirements."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            now = datetime.now(timezone.utc)
            recent_cutoff = now - timedelta(days=recent_days)
            baseline_cutoff = now - timedelta(days=baseline_days)
            
            # Get baseline distribution
            baseline_dist = {}
            for row in conn.execute("""
                SELECT experience_level, COUNT(*) as cnt
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ? AND timestamp < ?
                  AND experience_level IS NOT NULL
                GROUP BY experience_level
            """, (skill_id, baseline_cutoff.isoformat(), recent_cutoff.isoformat())):
                baseline_dist[row["experience_level"]] = row["cnt"]
            
            # Get recent distribution
            recent_dist = {}
            for row in conn.execute("""
                SELECT experience_level, COUNT(*) as cnt
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ?
                  AND experience_level IS NOT NULL
                GROUP BY experience_level
            """, (skill_id, recent_cutoff.isoformat())):
                recent_dist[row["experience_level"]] = row["cnt"]
        
        if not baseline_dist or not recent_dist:
            return None
        
        # Normalize distributions
        baseline_total = sum(baseline_dist.values())
        recent_total = sum(recent_dist.values())
        
        baseline_norm = {k: v / baseline_total for k, v in baseline_dist.items()}
        recent_norm = {k: v / recent_total for k, v in recent_dist.items()}
        
        # Calculate drift magnitude (Jensen-Shannon divergence approximation)
        all_levels = set(baseline_norm) | set(recent_norm)
        drift = 0
        for level in all_levels:
            p = baseline_norm.get(level, 0)
            q = recent_norm.get(level, 0)
            drift += abs(p - q)
        drift /= 2  # Normalize to 0-1
        
        if drift >= self._experience_drift_threshold:
            return SkillDrift(
                skill_id=skill_id,
                drift_type="experience_shift",
                old_value=baseline_dist,
                new_value=recent_dist,
                magnitude=drift,
                evidence=[
                    f"Baseline: {baseline_dist}",
                    f"Recent: {recent_dist}",
                ],
                recommended_action="Review skill requirements and update career paths",
            )
        
        return None
    
    def detect_industry_drift(
        self,
        skill_id: str,
        baseline_days: int = 90,
        recent_days: int = 30,
    ) -> Optional[SkillDrift]:
        """Detect drift in industry distribution."""
        # Similar structure to experience drift
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            now = datetime.now(timezone.utc)
            recent_cutoff = now - timedelta(days=recent_days)
            baseline_cutoff = now - timedelta(days=baseline_days)
            
            baseline_dist = {}
            for row in conn.execute("""
                SELECT industry, COUNT(*) as cnt
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ? AND timestamp < ?
                  AND industry IS NOT NULL
                GROUP BY industry
            """, (skill_id, baseline_cutoff.isoformat(), recent_cutoff.isoformat())):
                baseline_dist[row["industry"]] = row["cnt"]
            
            recent_dist = {}
            for row in conn.execute("""
                SELECT industry, COUNT(*) as cnt
                FROM skill_observations
                WHERE skill_id = ? AND timestamp >= ?
                  AND industry IS NOT NULL
                GROUP BY industry
            """, (skill_id, recent_cutoff.isoformat())):
                recent_dist[row["industry"]] = row["cnt"]
        
        if not baseline_dist or not recent_dist:
            return None
        
        # Normalize and calculate drift
        baseline_total = sum(baseline_dist.values())
        recent_total = sum(recent_dist.values())
        
        baseline_norm = {k: v / baseline_total for k, v in baseline_dist.items()}
        recent_norm = {k: v / recent_total for k, v in recent_dist.items()}
        
        all_industries = set(baseline_norm) | set(recent_norm)
        drift = sum(abs(baseline_norm.get(i, 0) - recent_norm.get(i, 0)) for i in all_industries) / 2
        
        if drift >= self._industry_drift_threshold:
            return SkillDrift(
                skill_id=skill_id,
                drift_type="industry_migration",
                old_value=baseline_dist,
                new_value=recent_dist,
                magnitude=drift,
                evidence=[
                    f"Skill migrating across industries",
                    f"New industries: {set(recent_dist) - set(baseline_dist)}",
                ],
                recommended_action="Update industry relevance mappings",
            )
        
        return None
    
    def detect_all_drifts(
        self,
        skill_id: str,
    ) -> List[SkillDrift]:
        """Run all drift detections for a skill."""
        drifts = []
        
        exp_drift = self.detect_experience_drift(skill_id)
        if exp_drift:
            drifts.append(exp_drift)
        
        ind_drift = self.detect_industry_drift(skill_id)
        if ind_drift:
            drifts.append(ind_drift)
        
        return drifts


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_detector: Optional[TrendDetector] = None


def get_trend_detector() -> TrendDetector:
    """Get singleton TrendDetector instance."""
    global _detector
    if _detector is None:
        _detector = TrendDetector()
    return _detector
