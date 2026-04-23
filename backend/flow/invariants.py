# backend/flow/invariants.py
"""
PRODUCTION HARDENING: Invariant Enforcement
============================================

HARDENING PRINCIPLES:
1. Ranking order is immutable after SIMGR scoring
2. All outputs are deterministically verifiable via checksum
3. No bypass of state machine execution context
4. RuleEngine cannot reorder, inject, or remove careers

INVARIANT CATEGORIES:
    I.   RANKING_IMMUTABILITY  - Ranking locked after SIMGR
    II.  DETERMINISTIC_CHECKSUM - SHA256 output verification
    III. ANTI_BYPASS           - Execution context guards
    IV.  STRICT_SCHEMA         - No implicit type coercion
    V.   NON_REORDER_GUARANTEE - RuleEngine cannot reorder

Author: System Architecture Team
Date: 2026-02-21
Status: PRODUCTION HARDENING
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple, TypeVar

logger = logging.getLogger("flow.invariants")


# ═══════════════════════════════════════════════════════════════════════════════
#  HARDENING ERROR TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class InvariantViolationType(Enum):
    """Types of invariant violations (all are fatal)."""
    
    # Ranking Invariants
    RANKING_REORDER_DETECTED = "RANKING_REORDER_DETECTED"
    RANKING_ORDER_MISMATCH = "RANKING_ORDER_MISMATCH"
    
    # Determinism Invariants
    DETERMINISTIC_INVARIANCE_ERROR = "DETERMINISTIC_INVARIANCE_ERROR"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    
    # Bypass Invariants
    UNAUTHORIZED_SCORING_ACCESS = "UNAUTHORIZED_SCORING_ACCESS"
    MISSING_EXECUTION_CONTEXT = "MISSING_EXECUTION_CONTEXT"
    INVALID_STATE_FOR_SCORING = "INVALID_STATE_FOR_SCORING"
    
    # RuleEngine Invariants
    CAREER_COUNT_MISMATCH = "CAREER_COUNT_MISMATCH"
    CAREER_ORDER_VIOLATED = "CAREER_ORDER_VIOLATED"
    CAREER_INJECTION_DETECTED = "CAREER_INJECTION_DETECTED"
    CAREER_REMOVAL_DETECTED = "CAREER_REMOVAL_DETECTED"


class InvariantViolationError(Exception):
    """
    Fatal error: Invariant violation detected.
    
    This error indicates a determinism or security violation.
    MUST NOT be caught and ignored - system should halt.
    """
    
    def __init__(
        self,
        violation_type: InvariantViolationType,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.violation_type = violation_type
        self.context = context or {}
        self.timestamp = time.time()
        
        # Log immediately (fatal errors must be recorded)
        logger.critical(
            f"INVARIANT VIOLATION: {violation_type.value} - {message}",
            extra={"context": self.context},
        )
        
        super().__init__(f"[{violation_type.value}] {message}")


class UnauthorizedScoringAccessError(InvariantViolationError):
    """Raised when SIMGRScorer is accessed without valid context."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            InvariantViolationType.UNAUTHORIZED_SCORING_ACCESS,
            message,
            context,
        )


class DeterministicInvarianceError(InvariantViolationError):
    """Raised when deterministic output checksum mismatches."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            InvariantViolationType.DETERMINISTIC_INVARIANCE_ERROR,
            message,
            context,
        )


class RankingOrderViolationError(InvariantViolationError):
    """Raised when ranking order is modified after SIMGR scoring."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            InvariantViolationType.RANKING_ORDER_MISMATCH,
            message,
            context,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  I. RANKING IMMUTABILITY ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RankingSnapshot:
    """
    Immutable snapshot of career ranking order.
    
    INVARIANT: Ranking order is immutable after SIMGR scoring.
    
    Captured immediately after SIMGRScorer.score() returns.
    Used to verify RuleEngine did not reorder results.
    """
    career_order: Tuple[str, ...]  # Ordered list of career names
    career_scores: Tuple[Tuple[str, float], ...]  # (name, raw_score) pairs
    timestamp: float
    checksum: str  # SHA256 of serialized order
    
    @classmethod
    def capture(cls, careers: List[Dict[str, Any]]) -> "RankingSnapshot":
        """
        Capture ranking snapshot from SIMGRScorer output.
        
        MUST be called immediately after SIMGRScorer.score().
        """
        # Extract ordered career names and scores
        career_order = tuple(c["name"] for c in careers)
        career_scores = tuple((c["name"], c.get("raw_score", c.get("final_score", 0.0))) for c in careers)
        
        # Compute checksum for verification
        order_data = json.dumps({"order": career_order, "scores": career_scores}, sort_keys=True)
        checksum = hashlib.sha256(order_data.encode("utf-8")).hexdigest()
        
        return cls(
            career_order=career_order,
            career_scores=career_scores,
            timestamp=time.time(),
            checksum=checksum,
        )
    
    def verify_order_preserved(self, final_careers: List[Dict[str, Any]]) -> None:
        """
        Verify that ranking order has not changed.
        
        Called after RuleEngine.process_profile() returns.
        
        Raises:
            RankingOrderViolationError: If order has changed
        """
        final_order = tuple(c["name"] for c in final_careers)
        
        # INVARIANT: original_rank_order == final_rank_order
        if self.career_order != final_order:
            raise RankingOrderViolationError(
                "Ranking order is immutable after SIMGR scoring. "
                f"Original: {self.career_order}, Final: {final_order}",
                context={
                    "original_order": self.career_order,
                    "final_order": final_order,
                    "snapshot_checksum": self.checksum,
                },
            )
        
        logger.debug("Ranking order verification PASSED")


class RankingImmutabilityEnforcer:
    """
    Enforces ranking immutability after SIMGR scoring.
    
    RULE: score_delta from RuleEngine may adjust metadata only,
          NOT reorder the ranking.
    
    Usage:
        enforcer = RankingImmutabilityEnforcer()
        snapshot = enforcer.lock_ranking(simgr_careers)
        # ... RuleEngine processes ...
        enforcer.verify_ranking(snapshot, final_careers)
    """
    
    def __init__(self):
        self._active_locks: Dict[str, RankingSnapshot] = {}
    
    def lock_ranking(
        self,
        session_id: str,
        careers: List[Dict[str, Any]],
    ) -> RankingSnapshot:
        """
        Lock ranking order after SIMGR scoring.
        
        Ranking order is immutable after SIMGR scoring.
        
        Returns:
            RankingSnapshot for verification
        """
        snapshot = RankingSnapshot.capture(careers)
        self._active_locks[session_id] = snapshot
        
        logger.info(
            f"Ranking LOCKED for session {session_id}: "
            f"{len(careers)} careers, checksum={snapshot.checksum[:16]}..."
        )
        
        return snapshot
    
    def verify_ranking(
        self,
        session_id: str,
        final_careers: List[Dict[str, Any]],
    ) -> None:
        """
        Verify ranking order has not changed.
        
        Raises:
            RankingOrderViolationError: If order modified
            ValueError: If no lock exists for session
        """
        if session_id not in self._active_locks:
            raise ValueError(f"No ranking lock exists for session {session_id}")
        
        snapshot = self._active_locks[session_id]
        snapshot.verify_order_preserved(final_careers)
    
    def release_lock(self, session_id: str) -> None:
        """Release ranking lock (cleanup)."""
        self._active_locks.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  II. DETERMINISTIC CHECKSUM VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DeterministicChecksum:
    """
    Immutable checksum of session output.
    
    Components:
        1. Ordered career list (by rank)
        2. Final scores (raw, not adjusted)
        3. Flags (sorted alphabetically)
        4. Warnings (sorted alphabetically)
    """
    session_id: str
    checksum: str
    components: Tuple[str, ...]  # What was hashed
    timestamp: float
    
    @classmethod
    def compute(
        cls,
        session_id: str,
        careers: List[Dict[str, Any]],
    ) -> "DeterministicChecksum":
        """
        Compute deterministic checksum from RESULT state.
        
        Returns:
            DeterministicChecksum for verification
        """
        # 1. Serialize ordered career list
        ordered_careers = sorted(careers, key=lambda c: c.get("rank", 0))
        career_names = [c["name"] for c in ordered_careers]
        
        # 2. Serialize final scores (raw)
        # Use raw_score if available, otherwise use final_score for ordering
        raw_scores = [
            c.get("raw_score", c.get("final_score", 0.0))
            for c in ordered_careers
        ]
        
        # 3. Serialize flags (sorted per career)
        all_flags = []
        for c in ordered_careers:
            flags = sorted(c.get("flags", []))
            all_flags.append(flags)
        
        # 4. Serialize warnings (sorted per career)
        all_warnings = []
        for c in ordered_careers:
            warnings = sorted(c.get("warnings", []))
            all_warnings.append(warnings)
        
        # Build canonical JSON for hashing
        canonical = {
            "session_id": session_id,
            "careers": career_names,
            "scores": raw_scores,
            "flags": all_flags,
            "warnings": all_warnings,
        }
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        
        # Generate SHA256 hash
        checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        
        return cls(
            session_id=session_id,
            checksum=checksum,
            components=("careers", "scores", "flags", "warnings"),
            timestamp=time.time(),
        )


class DeterministicOutputValidator:
    """
    Validates deterministic output via SHA256 checksum.
    
    INVARIANT: Same input → same output → same checksum
    
    Usage:
        validator = DeterministicOutputValidator()
        checksum = validator.generate_checksum(session_id, careers)
        # Store checksum
        # On replay:
        validator.verify_checksum(session_id, careers, stored_checksum)
    """
    
    def __init__(self):
        self._session_checksums: Dict[str, DeterministicChecksum] = {}
    
    def generate_checksum(
        self,
        session_id: str,
        careers: List[Dict[str, Any]],
    ) -> DeterministicChecksum:
        """
        Generate and store checksum for session.
        
        Called at RESULT state generation.
        """
        checksum = DeterministicChecksum.compute(session_id, careers)
        self._session_checksums[session_id] = checksum
        
        logger.info(
            f"Checksum generated for session {session_id}: {checksum.checksum[:16]}..."
        )
        
        return checksum
    
    def verify_checksum(
        self,
        session_id: str,
        careers: List[Dict[str, Any]],
        expected_checksum: Optional[str] = None,
    ) -> None:
        """
        Verify output matches expected checksum.
        
        If expected_checksum is None, uses stored checksum.
        
        Raises:
            DeterministicInvarianceError: If checksum mismatches
        """
        # Compute current checksum
        current = DeterministicChecksum.compute(session_id, careers)
        
        # Get expected checksum
        if expected_checksum:
            expected = expected_checksum
        elif session_id in self._session_checksums:
            expected = self._session_checksums[session_id].checksum
        else:
            raise ValueError(f"No stored checksum for session {session_id}")
        
        # INVARIANT: checksums must match
        if current.checksum != expected:
            raise DeterministicInvarianceError(
                f"Checksum mismatch for session {session_id}. "
                f"Expected: {expected[:16]}..., Got: {current.checksum[:16]}...",
                context={
                    "session_id": session_id,
                    "expected_checksum": expected,
                    "actual_checksum": current.checksum,
                },
            )
        
        logger.debug(f"Checksum verification PASSED for session {session_id}")
    
    def get_checksum(self, session_id: str) -> Optional[str]:
        """Get stored checksum for session."""
        if session_id in self._session_checksums:
            return self._session_checksums[session_id].checksum
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  III. ANTI-BYPASS ENFORCEMENT (EXECUTION CONTEXT)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ExecutionContext:
    """
    Required context for SIMGRScorer and RuleEngine execution.
    
    INVARIANT: Scoring operations MUST have valid ExecutionContext.
    
    Must contain:
        - session_id: Valid session UUID
        - trace_id: Unique trace for this execution
        - state: Must be SCORING for SIMGRScorer
    """
    session_id: str
    trace_id: str
    state: str
    timestamp: float = field(default_factory=time.time)
    
    # Valid states for scoring
    VALID_SCORING_STATES: FrozenSet[str] = frozenset({"scoring"})
    VALID_DECISION_STATES: FrozenSet[str] = frozenset({"decision"})
    
    def validate_for_scoring(self) -> None:
        """
        Validate context is valid for SIMGRScorer.
        
        Raises:
            UnauthorizedScoringAccessError: If context invalid
        """
        if not self.session_id:
            raise UnauthorizedScoringAccessError(
                "Missing session_id in execution context",
                context={"trace_id": self.trace_id},
            )
        
        if not self.trace_id:
            raise UnauthorizedScoringAccessError(
                "Missing trace_id in execution context",
                context={"session_id": self.session_id},
            )
        
        if self.state not in self.VALID_SCORING_STATES:
            raise UnauthorizedScoringAccessError(
                f"Invalid state for scoring. Required: SCORING, Got: {self.state}",
                context={
                    "session_id": self.session_id,
                    "trace_id": self.trace_id,
                    "state": self.state,
                },
            )
    
    def validate_for_decision(self) -> None:
        """
        Validate context is valid for RuleEngine.
        
        Raises:
            UnauthorizedScoringAccessError: If context invalid
        """
        if not self.session_id:
            raise UnauthorizedScoringAccessError(
                "Missing session_id in execution context",
                context={"trace_id": self.trace_id},
            )
        
        if self.state not in self.VALID_DECISION_STATES:
            raise UnauthorizedScoringAccessError(
                f"Invalid state for decision. Required: DECISION, Got: {self.state}",
                context={
                    "session_id": self.session_id,
                    "trace_id": self.trace_id,
                    "state": self.state,
                },
            )


def create_execution_context(
    session_id: str,
    state: str,
) -> ExecutionContext:
    """
    Factory function to create valid ExecutionContext.
    
    Should ONLY be called by StateMachine during state execution.
    """
    import uuid
    return ExecutionContext(
        session_id=session_id,
        trace_id=str(uuid.uuid4()),
        state=state,
        timestamp=time.time(),
    )


T = TypeVar("T", bound=Callable[..., Any])


def require_execution_context(valid_states: FrozenSet[str]) -> Callable[[T], T]:
    """
    Decorator to require valid ExecutionContext.
    
    Usage:
        @require_execution_context(frozenset({"scoring"}))
        def score(self, input_dict: Dict, context: ExecutionContext):
            ...
    """
    def decorator(func: T) -> T:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Find context in arguments
            context = kwargs.get("context")
            if context is None:
                # Try positional arguments
                for arg in args:
                    if isinstance(arg, ExecutionContext):
                        context = arg
                        break
            
            if context is None:
                raise UnauthorizedScoringAccessError(
                    f"Missing ExecutionContext for {func.__name__}",
                    context={"function": func.__name__},
                )
            
            if not isinstance(context, ExecutionContext):
                raise UnauthorizedScoringAccessError(
                    f"Invalid ExecutionContext type for {func.__name__}",
                    context={"function": func.__name__, "type": type(context).__name__},
                )
            
            if context.state not in valid_states:
                raise UnauthorizedScoringAccessError(
                    f"Invalid state for {func.__name__}. "
                    f"Required: {valid_states}, Got: {context.state}",
                    context={"function": func.__name__, "state": context.state},
                )
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
#  IV. STRICT STATE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

class StateTransitionGuard:
    """
    Enforces Controller.dispatch pattern for state transitions.
    
    INVARIANT: All transitions must go through dispatch().
    INVARIANT: Direct state mutation is forbidden.
    """
    
    def __init__(self):
        self._transition_log: List[Dict[str, Any]] = []
        self._dispatch_active: bool = False
    
    def enter_dispatch(self) -> None:
        """Mark dispatch as active."""
        self._dispatch_active = True
    
    def exit_dispatch(self) -> None:
        """Mark dispatch as inactive."""
        self._dispatch_active = False
    
    def verify_dispatch_active(self) -> None:
        """
        Verify we're inside dispatch().
        
        Raises:
            InvariantViolationError: If not in dispatch
        """
        if not self._dispatch_active:
            raise InvariantViolationError(
                InvariantViolationType.MISSING_EXECUTION_CONTEXT,
                "State transition attempted outside dispatch(). "
                "All transitions must go through dispatch().",
            )
    
    def log_transition(
        self,
        session_id: str,
        from_state: str,
        to_state: str,
        event: str,
    ) -> None:
        """Log transition for audit."""
        self._transition_log.append({
            "session_id": session_id,
            "from_state": from_state,
            "to_state": to_state,
            "event": event,
            "timestamp": time.time(),
        })


# ═══════════════════════════════════════════════════════════════════════════════
#  V. RULEENGINE NON-REORDER GUARANTEE
# ═══════════════════════════════════════════════════════════════════════════════

class RuleEngineGuard:
    """
    Enforces RuleEngine non-reorder guarantee.
    
    RuleEngine MAY:
        - Add flags
        - Add warnings
        - Reduce confidence
    
    RuleEngine MAY NOT:
        - Modify career ordering
        - Re-sort results
        - Inject new career
        - Remove existing career
    
    Runtime assertions:
        len(raw_careers) == len(final_careers)
        raw_order == final_order
    """
    
    @staticmethod
    def assert_no_reorder(
        raw_careers: List[Dict[str, Any]],
        final_careers: List[Dict[str, Any]],
    ) -> None:
        """
        Assert RuleEngine did not reorder, inject, or remove careers.
        
        Raises:
            InvariantViolationError: If any violation detected
        """
        # INVARIANT: len(raw_careers) == len(final_careers)
        if len(raw_careers) != len(final_careers):
            if len(raw_careers) > len(final_careers):
                raise InvariantViolationError(
                    InvariantViolationType.CAREER_REMOVAL_DETECTED,
                    f"RuleEngine removed careers. "
                    f"Raw count: {len(raw_careers)}, Final count: {len(final_careers)}",
                    context={
                        "raw_count": len(raw_careers),
                        "final_count": len(final_careers),
                    },
                )
            else:
                raise InvariantViolationError(
                    InvariantViolationType.CAREER_INJECTION_DETECTED,
                    f"RuleEngine injected new careers. "
                    f"Raw count: {len(raw_careers)}, Final count: {len(final_careers)}",
                    context={
                        "raw_count": len(raw_careers),
                        "final_count": len(final_careers),
                    },
                )
        
        # INVARIANT: raw_order == final_order
        raw_names = [c.get("name", "") for c in raw_careers]
        final_names = [c.get("name", "") for c in final_careers]
        
        if raw_names != final_names:
            raise InvariantViolationError(
                InvariantViolationType.CAREER_ORDER_VIOLATED,
                f"RuleEngine reordered careers. "
                f"This is forbidden. Ranking order is immutable after SIMGR scoring.",
                context={
                    "raw_order": raw_names,
                    "final_order": final_names,
                },
            )
        
        logger.debug("RuleEngine non-reorder assertion PASSED")
    
    @staticmethod
    def apply_rule_result_safely(
        raw_careers: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Apply RuleEngine result to careers WITHOUT reordering.
        
        Only applies:
            - flags (added)
            - warnings (added)
        
        Does NOT change:
            - career order
            - career names
            - raw scores for ranking
        
        Returns:
            Updated career list with metadata only
        """
        # Deep copy to avoid mutation
        import copy
        result = copy.deepcopy(raw_careers)
        
        # Apply flags by career name
        flags_by_career = rule_result.get("flags_by_career", {})
        warnings_by_career = rule_result.get("warnings_by_career", {})
        
        for career in result:
            name = career.get("name", "")
            
            # Add flags (do not replace)
            existing_flags = career.get("flags", [])
            new_flags = flags_by_career.get(name, [])
            career["flags"] = list(set(existing_flags) | set(new_flags))
            
            # Add warnings (do not replace)
            existing_warnings = career.get("warnings", [])
            new_warnings = warnings_by_career.get(name, [])
            career["warnings"] = list(set(existing_warnings) | set(new_warnings))
        
        # Verify no reordering occurred
        RuleEngineGuard.assert_no_reorder(raw_careers, result)
        
        return result


# ═══════════════════════════════════════════════════════════════════════════════
#  VI. COMBINED HARDENING CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

class ProductionHardeningController:
    """
    Combined controller for all hardening enforcement.
    
    Usage:
        hardening = ProductionHardeningController()
        
        # At SCORING completion:
        hardening.lock_ranking(session_id, simgr_careers)
        
        # At DECISION completion:
        final_careers = hardening.apply_decision_safely(session_id, simgr_careers, rule_result)
        
        # At RESULT generation:
        hardening.generate_and_verify_checksum(session_id, final_careers)
    """
    
    def __init__(self):
        self._ranking_enforcer = RankingImmutabilityEnforcer()
        self._checksum_validator = DeterministicOutputValidator()
        self._transition_guard = StateTransitionGuard()
    
    def create_scoring_context(self, session_id: str) -> ExecutionContext:
        """Create valid ExecutionContext for SCORING state."""
        return create_execution_context(session_id, "scoring")
    
    def create_decision_context(self, session_id: str) -> ExecutionContext:
        """Create valid ExecutionContext for DECISION state."""
        return create_execution_context(session_id, "decision")
    
    def lock_ranking(
        self,
        session_id: str,
        simgr_careers: List[Dict[str, Any]],
    ) -> RankingSnapshot:
        """
        Lock ranking order after SIMGR scoring.
        
        MUST be called immediately after SIMGRScorer.score().
        """
        return self._ranking_enforcer.lock_ranking(session_id, simgr_careers)
    
    def apply_decision_safely(
        self,
        session_id: str,
        simgr_careers: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Apply RuleEngine result safely (no reordering).
        
        Verifies:
            1. Ranking order preserved
            2. No career injection
            3. No career removal
        
        Returns:
            Final careers with flags/warnings applied
        """
        # Apply rule result safely
        final_careers = RuleEngineGuard.apply_rule_result_safely(
            simgr_careers, rule_result
        )
        
        # Verify ranking preserved
        self._ranking_enforcer.verify_ranking(session_id, final_careers)
        
        return final_careers
    
    def generate_and_verify_checksum(
        self,
        session_id: str,
        final_careers: List[Dict[str, Any]],
        expected_checksum: Optional[str] = None,
    ) -> str:
        """
        Generate and optionally verify checksum.
        
        If expected_checksum provided, verifies match.
        
        Returns:
            Generated checksum
        """
        checksum = self._checksum_validator.generate_checksum(session_id, final_careers)
        
        if expected_checksum:
            self._checksum_validator.verify_checksum(
                session_id, final_careers, expected_checksum
            )
        
        return checksum.checksum
    
    def release_session(self, session_id: str) -> None:
        """Release all locks for session (cleanup)."""
        self._ranking_enforcer.release_lock(session_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  MODULE EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Error Types
    "InvariantViolationType",
    "InvariantViolationError",
    "UnauthorizedScoringAccessError",
    "DeterministicInvarianceError",
    "RankingOrderViolationError",
    # Ranking Immutability
    "RankingSnapshot",
    "RankingImmutabilityEnforcer",
    # Deterministic Checksum
    "DeterministicChecksum",
    "DeterministicOutputValidator",
    # Execution Context
    "ExecutionContext",
    "create_execution_context",
    "require_execution_context",
    # State Guards
    "StateTransitionGuard",
    "RuleEngineGuard",
    # Combined Controller
    "ProductionHardeningController",
]
