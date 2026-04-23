# backend/ops/cost/budget_manager.py
"""
Budget Manager
==============

Enterprise-grade budget management system:
- Budget CRUD operations
- Period management
- Hierarchical budget tracking
- Multi-scope support
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.ops.cost.models import (
    AlertLevel,
    BudgetDefinition,
    BudgetPeriod,
    BudgetScope,
    BudgetStatus,
    BudgetThreshold,
    CostCategory,
    CostEntry,
    DEFAULT_BUDGETS,
    EnforcementAction,
    LimitType,
)

logger = logging.getLogger("ops.cost.budget_manager")


class BudgetManager:
    """
    Central budget management system.
    
    Features:
    - Budget CRUD with validation
    - Period calculation (daily/weekly/monthly/quarterly/annual)
    - Budget status tracking
    - Hierarchical budget support
    - SQLite persistence
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/ops/budgets.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()
        self._init_default_budgets()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS budgets (
                    budget_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    limit_type TEXT NOT NULL,
                    thresholds TEXT,
                    categories TEXT,
                    enabled INTEGER DEFAULT 1,
                    rollover INTEGER DEFAULT 0,
                    parent_budget_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT
                );
                
                CREATE TABLE IF NOT EXISTS cost_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    quantity REAL DEFAULT 1.0,
                    unit TEXT DEFAULT 'unit',
                    service TEXT,
                    user_id TEXT,
                    project_id TEXT,
                    model_id TEXT,
                    trace_id TEXT,
                    description TEXT,
                    metadata TEXT
                );
                
                CREATE TABLE IF NOT EXISTS budget_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id TEXT NOT NULL,
                    alert_level TEXT NOT NULL,
                    utilization REAL NOT NULL,
                    action_taken TEXT,
                    timestamp TEXT NOT NULL,
                    acknowledged INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    resolved_at TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_entries(timestamp);
                CREATE INDEX IF NOT EXISTS idx_cost_category ON cost_entries(category);
                CREATE INDEX IF NOT EXISTS idx_cost_service ON cost_entries(service);
                CREATE INDEX IF NOT EXISTS idx_budget_scope ON budgets(scope, scope_id);
            """)
    
    def _init_default_budgets(self) -> None:
        """Initialize default budget templates."""
        for budget in DEFAULT_BUDGETS.values():
            existing = self.get_budget(budget.budget_id)
            if not existing:
                self.create_budget(budget)
                logger.info(f"Created default budget: {budget.name}")
    
    # ═══════════════════════════════════════════════════════════════════
    # Budget CRUD
    # ═══════════════════════════════════════════════════════════════════
    
    def create_budget(self, budget: BudgetDefinition) -> BudgetDefinition:
        """Create a new budget definition."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO budgets 
                    (budget_id, name, description, scope, scope_id, period,
                     amount_usd, limit_type, thresholds, categories, enabled,
                     rollover, parent_budget_id, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    budget.budget_id,
                    budget.name,
                    budget.description,
                    budget.scope.value,
                    budget.scope_id,
                    budget.period.value,
                    budget.amount_usd,
                    budget.limit_type.value,
                    json.dumps([t.to_dict() for t in budget.thresholds]),
                    json.dumps([c.value for c in budget.categories]),
                    1 if budget.enabled else 0,
                    1 if budget.rollover else 0,
                    budget.parent_budget_id,
                    budget.created_at,
                    budget.updated_at,
                    json.dumps(budget.metadata),
                ))
        logger.info(f"Budget created: {budget.budget_id}")
        return budget
    
    def get_budget(self, budget_id: str) -> Optional[BudgetDefinition]:
        """Get a budget by ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM budgets WHERE budget_id = ?",
                (budget_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_budget(dict(row))
    
    def list_budgets(
        self,
        scope: Optional[BudgetScope] = None,
        scope_id: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[BudgetDefinition]:
        """List budgets with optional filters."""
        query = "SELECT * FROM budgets WHERE 1=1"
        params: List[Any] = []
        
        if scope:
            query += " AND scope = ?"
            params.append(scope.value)
        
        if scope_id:
            query += " AND scope_id = ?"
            params.append(scope_id)
        
        if enabled_only:
            query += " AND enabled = 1"
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_budget(dict(r)) for r in rows]
    
    def update_budget(
        self,
        budget_id: str,
        updates: Dict[str, Any],
    ) -> Optional[BudgetDefinition]:
        """Update a budget definition."""
        budget = self.get_budget(budget_id)
        if not budget:
            return None
        
        # Apply updates
        if "amount_usd" in updates:
            budget.amount_usd = updates["amount_usd"]
        if "enabled" in updates:
            budget.enabled = updates["enabled"]
        if "limit_type" in updates:
            budget.limit_type = LimitType(updates["limit_type"])
        if "thresholds" in updates:
            budget.thresholds = [BudgetThreshold.from_dict(t) for t in updates["thresholds"]]
        
        budget.updated_at = datetime.now(timezone.utc).isoformat()
        
        return self.create_budget(budget)
    
    def delete_budget(self, budget_id: str) -> bool:
        """Delete a budget."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.execute(
                    "DELETE FROM budgets WHERE budget_id = ?",
                    (budget_id,)
                )
                return cursor.rowcount > 0
    
    def _row_to_budget(self, row: Dict[str, Any]) -> BudgetDefinition:
        """Convert database row to BudgetDefinition."""
        thresholds = json.loads(row.get("thresholds") or "[]")
        categories = json.loads(row.get("categories") or "[]")
        
        return BudgetDefinition(
            budget_id=row["budget_id"],
            name=row["name"],
            description=row.get("description", ""),
            scope=BudgetScope(row["scope"]),
            scope_id=row["scope_id"],
            period=BudgetPeriod(row["period"]),
            amount_usd=row["amount_usd"],
            limit_type=LimitType(row.get("limit_type", "soft")),
            thresholds=[BudgetThreshold.from_dict(t) for t in thresholds],
            categories=[CostCategory(c) for c in categories],
            enabled=bool(row.get("enabled", 1)),
            rollover=bool(row.get("rollover", 0)),
            parent_budget_id=row.get("parent_budget_id"),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            metadata=json.loads(row.get("metadata") or "{}"),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Period Calculation
    # ═══════════════════════════════════════════════════════════════════
    
    def get_period_bounds(
        self,
        period: BudgetPeriod,
        reference_date: Optional[datetime] = None,
    ) -> Tuple[datetime, datetime]:
        """Get start and end dates for a budget period."""
        ref = reference_date or datetime.now(timezone.utc)
        
        if period == BudgetPeriod.DAILY:
            start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        
        elif period == BudgetPeriod.WEEKLY:
            start = ref - timedelta(days=ref.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        
        elif period == BudgetPeriod.MONTHLY:
            start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Next month
            if ref.month == 12:
                end = start.replace(year=ref.year + 1, month=1)
            else:
                end = start.replace(month=ref.month + 1)
        
        elif period == BudgetPeriod.QUARTERLY:
            quarter = (ref.month - 1) // 3
            start_month = quarter * 3 + 1
            start = ref.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            if start_month + 3 > 12:
                end = start.replace(year=ref.year + 1, month=(start_month + 3) - 12)
            else:
                end = start.replace(month=start_month + 3)
        
        elif period == BudgetPeriod.ANNUAL:
            start = ref.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=ref.year + 1)
        
        else:
            raise ValueError(f"Unknown period: {period}")
        
        return start, end
    
    # ═══════════════════════════════════════════════════════════════════
    # Cost Entry Management
    # ═══════════════════════════════════════════════════════════════════
    
    def record_cost(self, entry: CostEntry) -> CostEntry:
        """Record a cost entry."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cost_entries
                    (entry_id, timestamp, category, amount_usd, quantity, unit,
                     service, user_id, project_id, model_id, trace_id, description, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.entry_id,
                    entry.timestamp,
                    entry.category.value,
                    entry.amount_usd,
                    entry.quantity,
                    entry.unit,
                    entry.service,
                    entry.user_id,
                    entry.project_id,
                    entry.model_id,
                    entry.trace_id,
                    entry.description,
                    json.dumps(entry.metadata),
                ))
        return entry
    
    def get_costs_in_period(
        self,
        start: datetime,
        end: datetime,
        category: Optional[CostCategory] = None,
        service: Optional[str] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[CostEntry]:
        """Get cost entries within a time period."""
        query = """
            SELECT * FROM cost_entries 
            WHERE timestamp >= ? AND timestamp < ?
        """
        params: List[Any] = [start.isoformat(), end.isoformat()]
        
        if category:
            query += " AND category = ?"
            params.append(category.value)
        
        if service:
            query += " AND service = ?"
            params.append(service)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_cost_entry(dict(r)) for r in rows]
    
    def get_total_spent(
        self,
        start: datetime,
        end: datetime,
        categories: Optional[List[CostCategory]] = None,
        service: Optional[str] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> float:
        """Get total spent amount in a period."""
        query = """
            SELECT COALESCE(SUM(amount_usd), 0) as total
            FROM cost_entries 
            WHERE timestamp >= ? AND timestamp < ?
        """
        params: List[Any] = [start.isoformat(), end.isoformat()]
        
        if categories:
            placeholders = ",".join(["?" for _ in categories])
            query += f" AND category IN ({placeholders})"
            params.extend([c.value for c in categories])
        
        if service:
            query += " AND service = ?"
            params.append(service)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            result = conn.execute(query, params).fetchone()
            return result[0] if result else 0.0
    
    def _row_to_cost_entry(self, row: Dict[str, Any]) -> CostEntry:
        """Convert database row to CostEntry."""
        return CostEntry(
            entry_id=row["entry_id"],
            timestamp=row["timestamp"],
            category=CostCategory(row["category"]),
            amount_usd=row["amount_usd"],
            quantity=row.get("quantity", 1.0),
            unit=row.get("unit", "unit"),
            service=row.get("service", ""),
            user_id=row.get("user_id"),
            project_id=row.get("project_id"),
            model_id=row.get("model_id"),
            trace_id=row.get("trace_id"),
            description=row.get("description", ""),
            metadata=json.loads(row.get("metadata") or "{}"),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Budget Status
    # ═══════════════════════════════════════════════════════════════════
    
    def get_budget_status(self, budget_id: str) -> Optional[BudgetStatus]:
        """Get current status of a budget."""
        budget = self.get_budget(budget_id)
        if not budget:
            return None
        
        start, end = self.get_period_bounds(budget.period)
        
        # Calculate spent based on scope
        if budget.scope == BudgetScope.GLOBAL:
            spent = self.get_total_spent(start, end, budget.categories or None)
        elif budget.scope == BudgetScope.SERVICE:
            spent = self.get_total_spent(start, end, budget.categories or None, service=budget.scope_id)
        elif budget.scope == BudgetScope.USER:
            spent = self.get_total_spent(start, end, budget.categories or None, user_id=budget.scope_id)
        elif budget.scope == BudgetScope.PROJECT:
            spent = self.get_total_spent(start, end, budget.categories or None, project_id=budget.scope_id)
        else:
            spent = self.get_total_spent(start, end, budget.categories or None)
        
        remaining = max(0, budget.amount_usd - spent)
        utilization = spent / budget.amount_usd if budget.amount_usd > 0 else 0
        
        # Determine alert level
        alert_level = None
        for threshold in sorted(budget.thresholds, key=lambda t: t.percentage, reverse=True):
            if utilization >= threshold.percentage:
                alert_level = threshold.alert_level
                break
        
        return BudgetStatus(
            budget_id=budget.budget_id,
            budget_name=budget.name,
            period=budget.period,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            budget_amount=budget.amount_usd,
            spent_amount=spent,
            remaining_amount=remaining,
            utilization_percentage=utilization,
            current_alert_level=alert_level,
            is_exceeded=spent >= budget.amount_usd,
            is_hard_limited=(budget.limit_type == LimitType.HARD and spent >= budget.amount_usd),
        )
    
    def get_all_budget_statuses(self) -> List[BudgetStatus]:
        """Get status of all active budgets."""
        budgets = self.list_budgets(enabled_only=True)
        return [self.get_budget_status(b.budget_id) for b in budgets if self.get_budget_status(b.budget_id)]
    
    # ═══════════════════════════════════════════════════════════════════
    # Alerts
    # ═══════════════════════════════════════════════════════════════════
    
    def record_alert(
        self,
        budget_id: str,
        alert_level: AlertLevel,
        utilization: float,
        action_taken: Optional[EnforcementAction] = None,
    ) -> None:
        """Record a budget alert."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO budget_alerts
                    (budget_id, alert_level, utilization, action_taken, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    budget_id,
                    alert_level.value,
                    utilization,
                    action_taken.value if action_taken else None,
                    datetime.now(timezone.utc).isoformat(),
                ))
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent budget alerts."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM budget_alerts
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """, (cutoff,)).fetchall()
            
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_budget_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Get singleton BudgetManager instance."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager()
    return _budget_manager
