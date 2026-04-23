"""
Failure Catalog — Taxonomy of pipeline failure types.
=====================================================
Classifies every error into a category with recovery strategy metadata.

Categories:
  TRANSIENT  — network timeouts, rate limits, temporary 5xx  → retry
  DATA       — bad CSV, schema mismatch, validation fail     → skip / partial rollback
  CONFIG     — missing secrets, bad YAML, wrong thresholds   → abort + alert
  RESOURCE   — OOM, disk full, browser leak                  → cooldown + retry
  EXTERNAL   — 3rd-party API down, crawler blocked           → circuit-break + retry
  INTERNAL   — logic bug, assertion error                    → abort + alert

Each FailureEntry carries:
  • retryable: bool
  • max_retries override
  • recovery_strategy: RETRY | ROLLBACK_AND_RETRY | SKIP_STAGE | ABORT | ESCALATE
  • severity: low | medium | high | critical
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.recovery.catalog")


# ── Failure Category Enum ───────────────────────────────────────────────

class FailureCategory(str, Enum):
    TRANSIENT = "transient"
    DATA = "data"
    CONFIG = "config"
    RESOURCE = "resource"
    EXTERNAL = "external"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    RETRY = "retry"                       # retry same stage
    ROLLBACK_AND_RETRY = "rollback_retry"  # rollback then retry
    SKIP_STAGE = "skip_stage"             # skip, continue pipeline
    ABORT = "abort"                       # stop pipeline
    ESCALATE = "escalate"                 # alert human, pause


# ── Failure Entry ───────────────────────────────────────────────────────

@dataclass
class FailureEntry:
    """A registered pattern that classifies an error."""
    name: str
    category: FailureCategory
    pattern: str                           # regex matched against str(error)
    retryable: bool = True
    max_retries: int = 3
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY
    severity: str = "medium"               # low | medium | high | critical
    description: str = ""
    _compiled: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        self._compiled = re.compile(self.pattern, re.IGNORECASE)

    def matches(self, error: Exception) -> bool:
        text = f"{type(error).__name__}: {error}"
        return bool(self._compiled.search(text))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category.value,
            "pattern": self.pattern,
            "retryable": self.retryable,
            "max_retries": self.max_retries,
            "recovery_strategy": self.recovery_strategy.value,
            "severity": self.severity,
            "description": self.description,
        }


# ── Classified Failure ──────────────────────────────────────────────────

@dataclass
class ClassifiedFailure:
    """Result of classifying an error."""
    error: Exception
    category: FailureCategory
    entry: Optional[FailureEntry]
    stage: str
    run_id: str
    timestamp: float = field(default_factory=time.time)

    @property
    def retryable(self) -> bool:
        return self.entry.retryable if self.entry else False

    @property
    def max_retries(self) -> int:
        return self.entry.max_retries if self.entry else 0

    @property
    def recovery_strategy(self) -> RecoveryStrategy:
        if self.entry:
            return self.entry.recovery_strategy
        return RecoveryStrategy.ABORT

    @property
    def severity(self) -> str:
        return self.entry.severity if self.entry else "critical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": type(self.error).__name__,
            "error_msg": str(self.error)[:500],
            "category": self.category.value,
            "stage": self.stage,
            "run_id": self.run_id,
            "retryable": self.retryable,
            "max_retries": self.max_retries,
            "recovery_strategy": self.recovery_strategy.value,
            "severity": self.severity,
            "entry_name": self.entry.name if self.entry else None,
            "timestamp": self.timestamp,
        }


# ── Failure History ─────────────────────────────────────────────────────

@dataclass
class FailureRecord:
    """Persisted record of a past failure."""
    run_id: str
    stage: str
    category: str
    error_type: str
    error_msg: str
    recovery_strategy: str
    recovered: bool
    recovery_duration: float  # seconds
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "category": self.category,
            "error_type": self.error_type,
            "error_msg": self.error_msg[:300],
            "recovery_strategy": self.recovery_strategy,
            "recovered": self.recovered,
            "recovery_duration": round(self.recovery_duration, 2),
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════
#  FailureCatalog
# ═══════════════════════════════════════════════════════════════════════

class FailureCatalog:
    """
    Central registry of known failure patterns.

    Pre-loaded with ~25 patterns covering the common pipeline errors.
    Teams can register custom patterns at runtime.
    """

    def __init__(self) -> None:
        self._entries: List[FailureEntry] = []
        self._history: List[FailureRecord] = []
        self._max_history: int = 500
        self._load_builtin_entries()

    # ── Classification ──────────────────────────────────────────────

    def classify(
        self, error: Exception, stage: str = "", run_id: str = ""
    ) -> ClassifiedFailure:
        """Classify an error against registered patterns."""
        for entry in self._entries:
            if entry.matches(error):
                logger.debug(
                    f"Classified {type(error).__name__} as "
                    f"{entry.category.value}/{entry.name}"
                )
                return ClassifiedFailure(
                    error=error,
                    category=entry.category,
                    entry=entry,
                    stage=stage,
                    run_id=run_id,
                )

        # Unknown — default to INTERNAL / ABORT
        logger.warning(
            f"Unclassified error in stage '{stage}': "
            f"{type(error).__name__}: {str(error)[:200]}"
        )
        return ClassifiedFailure(
            error=error,
            category=FailureCategory.UNKNOWN,
            entry=None,
            stage=stage,
            run_id=run_id,
        )

    # ── Registration ────────────────────────────────────────────────

    def register(self, entry: FailureEntry) -> None:
        """Register a new failure pattern (prepended for priority)."""
        self._entries.insert(0, entry)

    def register_pattern(
        self,
        name: str,
        category: FailureCategory,
        pattern: str,
        *,
        retryable: bool = True,
        max_retries: int = 3,
        recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY,
        severity: str = "medium",
        description: str = "",
    ) -> FailureEntry:
        """Convenience: register a pattern by keyword args."""
        entry = FailureEntry(
            name=name,
            category=category,
            pattern=pattern,
            retryable=retryable,
            max_retries=max_retries,
            recovery_strategy=recovery_strategy,
            severity=severity,
            description=description,
        )
        self.register(entry)
        return entry

    # ── History ─────────────────────────────────────────────────────

    def record_failure(
        self,
        run_id: str,
        stage: str,
        classified: ClassifiedFailure,
        recovered: bool,
        recovery_duration: float = 0.0,
    ) -> FailureRecord:
        """Record a failure event to history."""
        record = FailureRecord(
            run_id=run_id,
            stage=stage,
            category=classified.category.value,
            error_type=type(classified.error).__name__,
            error_msg=str(classified.error)[:500],
            recovery_strategy=classified.recovery_strategy.value,
            recovered=recovered,
            recovery_duration=recovery_duration,
            timestamp=time.time(),
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return record

    def get_history(
        self,
        stage: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query failure history with optional filters."""
        results = self._history
        if stage:
            results = [r for r in results if r.stage == stage]
        if category:
            results = [r for r in results if r.category == category]
        return [r.to_dict() for r in results[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate failure statistics."""
        if not self._history:
            return {
                "total_failures": 0,
                "by_category": {},
                "by_stage": {},
                "recovery_rate": 1.0,
                "avg_recovery_time": 0.0,
            }

        by_cat: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        recovered_count = 0
        total_recovery_time = 0.0

        for r in self._history:
            by_cat[r.category] = by_cat.get(r.category, 0) + 1
            by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
            if r.recovered:
                recovered_count += 1
                total_recovery_time += r.recovery_duration

        total = len(self._history)
        return {
            "total_failures": total,
            "by_category": by_cat,
            "by_stage": by_stage,
            "recovery_rate": round(recovered_count / total, 4) if total else 1.0,
            "avg_recovery_time": (
                round(total_recovery_time / recovered_count, 2)
                if recovered_count else 0.0
            ),
        }

    # ── Catalog export ──────────────────────────────────────────────

    def list_entries(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entries]

    def get_entry(self, name: str) -> Optional[FailureEntry]:
        return next((e for e in self._entries if e.name == name), None)

    # ── Built-in patterns ───────────────────────────────────────────

    def _load_builtin_entries(self) -> None:
        """Pre-register ~25 patterns covering common pipeline failures."""
        builtins = [
            # ── TRANSIENT ────────────────────────────────────────
            FailureEntry(
                name="network_timeout",
                category=FailureCategory.TRANSIENT,
                pattern=r"timeout|timed?\s*out|connect.*timeout|read.*timeout",
                retryable=True, max_retries=3,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="medium",
                description="Network timeout — retryable with backoff",
            ),
            FailureEntry(
                name="connection_refused",
                category=FailureCategory.TRANSIENT,
                pattern=r"connection\s*(refused|reset|aborted)|ECONNREFUSED|ECONNRESET",
                retryable=True, max_retries=3,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="medium",
                description="Connection refused/reset — usually transient",
            ),
            FailureEntry(
                name="http_5xx",
                category=FailureCategory.TRANSIENT,
                pattern=r"50[0-4]|502\s*bad\s*gateway|503\s*service|500\s*internal",
                retryable=True, max_retries=3,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="medium",
                description="Server 5xx — transient HTTP error",
            ),
            FailureEntry(
                name="dns_resolution",
                category=FailureCategory.TRANSIENT,
                pattern=r"name.*resolution|DNS|getaddrinfo|NXDOMAIN",
                retryable=True, max_retries=2,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="high",
                description="DNS resolution failure",
            ),
            FailureEntry(
                name="ssl_error",
                category=FailureCategory.TRANSIENT,
                pattern=r"SSL|certificate|CERT_",
                retryable=True, max_retries=1,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="high",
                description="SSL/TLS handshake error",
            ),

            # ── EXTERNAL ─────────────────────────────────────────
            FailureEntry(
                name="rate_limit",
                category=FailureCategory.EXTERNAL,
                pattern=r"429|rate.?limit|too.?many.?requests|throttl",
                retryable=True, max_retries=5,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="medium",
                description="Rate limited — retry with longer backoff",
            ),
            FailureEntry(
                name="captcha_block",
                category=FailureCategory.EXTERNAL,
                pattern=r"captcha|cloudflare|challenge|bot.?detect",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.SKIP_STAGE,
                severity="high",
                description="Bot detection / CAPTCHA — cannot auto-recover",
            ),
            FailureEntry(
                name="api_auth_failure",
                category=FailureCategory.EXTERNAL,
                pattern=r"401|403|unauthorized|forbidden|invalid.?token|auth.*fail",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ESCALATE,
                severity="critical",
                description="Authentication/authorization failure",
            ),
            FailureEntry(
                name="crawler_blocked",
                category=FailureCategory.EXTERNAL,
                pattern=r"\bip.?block|\bbanned\b|geo.?restrict",
                retryable=True, max_retries=2,
                recovery_strategy=RecoveryStrategy.SKIP_STAGE,
                severity="high",
                description="Crawler IP blocked by target site",
            ),

            # ── DATA ─────────────────────────────────────────────
            FailureEntry(
                name="schema_mismatch",
                category=FailureCategory.DATA,
                pattern=r"schema|validation.*error|pydantic|field.*required|missing.*field",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="high",
                description="Data schema violation — rollback to clean data",
            ),
            FailureEntry(
                name="empty_dataset",
                category=FailureCategory.DATA,
                pattern=r"empty|no.*records|zero.*rows|no.*data|no.*csv",
                retryable=True, max_retries=2,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="high",
                description="Empty dataset — retry crawl or use fallback",
            ),
            FailureEntry(
                name="csv_parse_error",
                category=FailureCategory.DATA,
                pattern=r"csv|parse.*error|decode.*error|UnicodeDecodeError|codec",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.SKIP_STAGE,
                severity="medium",
                description="CSV/encoding parse error — skip corrupt file",
            ),
            FailureEntry(
                name="quality_gate_block",
                category=FailureCategory.DATA,
                pattern=r"quality.*gate|QualityGate.*BLOCKED|drift.*block|validation.*rate",
                retryable=True, max_retries=1,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="high",
                description="Quality gate blocked the pipeline",
            ),

            # ── RESOURCE ─────────────────────────────────────────
            FailureEntry(
                name="out_of_memory",
                category=FailureCategory.RESOURCE,
                pattern=r"MemoryError|OOM|out.?of.?memory|cannot.?alloc",
                retryable=True, max_retries=1,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="critical",
                description="Out of memory — need cooldown before retry",
            ),
            FailureEntry(
                name="disk_full",
                category=FailureCategory.RESOURCE,
                pattern=r"No space|disk.*full|ENOSPC|OSError.*28",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Disk full — cannot continue",
            ),
            FailureEntry(
                name="browser_crash",
                category=FailureCategory.RESOURCE,
                pattern=r"browser.*crash|playwright.*crash|chromium.*crash|Target.*closed",
                retryable=True, max_retries=2,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="high",
                description="Browser/Playwright crash — restart and retry",
            ),
            FailureEntry(
                name="browser_leak",
                category=FailureCategory.RESOURCE,
                pattern=r"leak.*detect|browser.*leak|zombie.*process",
                retryable=True, max_retries=1,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="high",
                description="Browser resource leak — cleanup then retry",
            ),
            FailureEntry(
                name="file_lock",
                category=FailureCategory.RESOURCE,
                pattern=r"lock|PermissionError|WinError.*32|file.*in.*use",
                retryable=True, max_retries=3,
                recovery_strategy=RecoveryStrategy.RETRY,
                severity="medium",
                description="File locked by another process",
            ),

            # ── CONFIG ───────────────────────────────────────────
            FailureEntry(
                name="missing_secret",
                category=FailureCategory.CONFIG,
                pattern=r"missing.*secret|API_KEY|secret.*not.*found|env.*not.*set",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Missing required secret/env var",
            ),
            FailureEntry(
                name="yaml_parse",
                category=FailureCategory.CONFIG,
                pattern=r"yaml|YAML|YAMLError|invalid.*config|config.*parse",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Config YAML parse error",
            ),
            FailureEntry(
                name="import_error",
                category=FailureCategory.CONFIG,
                pattern=r"ImportError|ModuleNotFoundError|No module named",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Missing Python module/dependency",
            ),

            # ── INTERNAL ─────────────────────────────────────────
            FailureEntry(
                name="assertion_error",
                category=FailureCategory.INTERNAL,
                pattern=r"AssertionError|assert.*fail",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Assertion failure — logic bug",
            ),
            FailureEntry(
                name="type_error",
                category=FailureCategory.INTERNAL,
                pattern=r"TypeError|AttributeError|NoneType",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="critical",
                description="Type/attribute error — likely code bug",
            ),
            FailureEntry(
                name="key_error",
                category=FailureCategory.INTERNAL,
                pattern=r"KeyError|IndexError",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ABORT,
                severity="high",
                description="Missing key/index — data structure mismatch",
            ),
            FailureEntry(
                name="pipeline_error",
                category=FailureCategory.INTERNAL,
                pattern=r"PipelineError",
                retryable=False, max_retries=0,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
                severity="high",
                description="Explicit pipeline error from stage logic",
            ),
        ]

        self._entries.extend(builtins)
        logger.debug(f"Loaded {len(builtins)} built-in failure patterns")
