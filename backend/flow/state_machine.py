# backend/flow/state_machine.py
"""
ONE-BUTTON FLOW: Deterministic State Machine
============================================

ARCHITECTURE COMPLIANCE:
-----------------------
- NO modification to SIMGRScorer
- NO modification to RuleEngine
- NO change in scoring weights
- NO chat-style API
- ALL decisions local deterministic

PRODUCTION HARDENING (2026-02-21):
---------------------------------
- I.   RANKING_IMMUTABILITY: Ranking locked after SIMGR scoring
- II.  DETERMINISTIC_CHECKSUM: SHA256 output verification
- III. ANTI_BYPASS: ExecutionContext required for scoring
- IV.  STRICT_SCHEMA: No implicit type coercion
- V.   NON_REORDER_GUARANTEE: RuleEngine cannot reorder careers

INVARIANT: Ranking order is immutable after SIMGR scoring.

STATE MACHINE:
    INIT → SESSION_CREATED → ASSESSMENT_RUNNING → VALIDATION
                                    ↓
    CLOSED ← RESULT ← EXPLAIN ← DECISION ← SCORING

INVARIANTS:
    1. Each session has exactly one state at any time
    2. Transitions are deterministic (same input → same next state)
    3. No external API calls during transitions
    4. State changes are atomic
    5. SIMGRScorer and RuleEngine called ONLY in SCORING/DECISION state
    6. Ranking order immutable after SIMGR scoring (HARDENED)
    7. Deterministic checksum verifiable (HARDENED)

Author: System Architecture Team
Date: 2026-02-21
Status: PRODUCTION HARDENED
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# HARDENING IMPORTS
from backend.flow.invariants import (
    ExecutionContext,
    ProductionHardeningController,
    RankingSnapshot,
    RuleEngineGuard,
    UnauthorizedScoringAccessError,
    create_execution_context,
)

logger = logging.getLogger("flow.state_machine")


# ═══════════════════════════════════════════════════════════════════════════════
#  I. STATE DEFINITIONS (FORMAL STATE MACHINE)
# ═══════════════════════════════════════════════════════════════════════════════

class SessionState(Enum):
    """
    One-Button Flow Session States.
    
    State Ordering (STRICT):
        INIT (0) → SESSION_CREATED (1) → ASSESSMENT_RUNNING (2) → VALIDATION (3)
             → SCORING (4) → DECISION (5) → EXPLAIN (6) → RESULT (7) → CLOSED (8)
    
    ERROR states can be entered from any non-terminal state.
    """
    INIT = (0, "init", False)
    SESSION_CREATED = (1, "session_created", False)
    ASSESSMENT_RUNNING = (2, "assessment_running", False)
    VALIDATION = (3, "validation", False)
    SCORING = (4, "scoring", False)
    DECISION = (5, "decision", False)
    EXPLAIN = (6, "explain", False)
    RESULT = (7, "result", False)
    CLOSED = (8, "closed", True)
    ERROR = (99, "error", True)
    
    def __init__(self, order: int, state_name: str, is_terminal: bool):
        self._order = order
        self._state_name = state_name
        self._is_terminal = is_terminal
    
    @property
    def order(self) -> int:
        return self._order
    
    @property
    def state_name(self) -> str:
        return self._state_name
    
    @property
    def is_terminal(self) -> bool:
        return self._is_terminal


class TransitionEvent(Enum):
    """Events that trigger state transitions."""
    START_SESSION = "start_session"
    SUBMIT_ANSWER = "submit_answer"
    SUBMIT_ASSESSMENT = "submit_assessment"
    VALIDATION_COMPLETE = "validation_complete"
    SCORING_COMPLETE = "scoring_complete"
    DECISION_COMPLETE = "decision_complete"
    EXPLAIN_COMPLETE = "explain_complete"
    GET_RESULT = "get_result"
    CLOSE_SESSION = "close_session"
    ERROR_OCCURRED = "error_occurred"


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE TRANSITION TABLE (FORMAL DEFINITION)
# ═══════════════════════════════════════════════════════════════════════════════

TRANSITION_TABLE: Dict[Tuple[SessionState, TransitionEvent], SessionState] = {
    # INIT transitions
    (SessionState.INIT, TransitionEvent.START_SESSION): SessionState.SESSION_CREATED,
    (SessionState.INIT, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # SESSION_CREATED transitions
    (SessionState.SESSION_CREATED, TransitionEvent.SUBMIT_ANSWER): SessionState.ASSESSMENT_RUNNING,
    (SessionState.SESSION_CREATED, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    (SessionState.SESSION_CREATED, TransitionEvent.CLOSE_SESSION): SessionState.CLOSED,
    
    # ASSESSMENT_RUNNING transitions
    (SessionState.ASSESSMENT_RUNNING, TransitionEvent.SUBMIT_ANSWER): SessionState.ASSESSMENT_RUNNING,  # Self-loop
    (SessionState.ASSESSMENT_RUNNING, TransitionEvent.SUBMIT_ASSESSMENT): SessionState.VALIDATION,
    (SessionState.ASSESSMENT_RUNNING, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    (SessionState.ASSESSMENT_RUNNING, TransitionEvent.CLOSE_SESSION): SessionState.CLOSED,
    
    # VALIDATION transitions
    (SessionState.VALIDATION, TransitionEvent.VALIDATION_COMPLETE): SessionState.SCORING,
    (SessionState.VALIDATION, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # SCORING transitions
    (SessionState.SCORING, TransitionEvent.SCORING_COMPLETE): SessionState.DECISION,
    (SessionState.SCORING, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # DECISION transitions
    (SessionState.DECISION, TransitionEvent.DECISION_COMPLETE): SessionState.EXPLAIN,
    (SessionState.DECISION, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # EXPLAIN transitions
    (SessionState.EXPLAIN, TransitionEvent.EXPLAIN_COMPLETE): SessionState.RESULT,
    (SessionState.EXPLAIN, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # RESULT transitions
    (SessionState.RESULT, TransitionEvent.GET_RESULT): SessionState.RESULT,  # Idempotent read
    (SessionState.RESULT, TransitionEvent.CLOSE_SESSION): SessionState.CLOSED,
    (SessionState.RESULT, TransitionEvent.ERROR_OCCURRED): SessionState.ERROR,
    
    # Terminal states have no outgoing transitions
    # CLOSED: no transitions
    # ERROR: no transitions (recovery requires new session)
}

# Valid events per state (precomputed)
VALID_EVENTS: Dict[SessionState, FrozenSet[TransitionEvent]] = {
    state: frozenset(
        event for (s, event) in TRANSITION_TABLE.keys() if s == state
    )
    for state in SessionState
}


# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION DATA MODELS (IMMUTABLE WHERE POSSIBLE)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AssessmentAnswer:
    """Single immutable answer."""
    question_id: str
    value: Any
    timestamp_ms: float
    response_time_ms: float


@dataclass
class SessionData:
    """
    Mutable session data container.
    
    Lifecycle:
        1. Created at SESSION_CREATED
        2. Answers added during ASSESSMENT_RUNNING
        3. Frozen at VALIDATION
        4. Read-only from SCORING onward
    
    HARDENING: Includes ranking snapshot and checksum for invariant verification.
    """
    session_id: str
    created_at: float
    answers: List[AssessmentAnswer] = field(default_factory=list)
    user_profile: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None
    scoring_result: Optional[Dict[str, Any]] = None
    decision_result: Optional[Dict[str, Any]] = None
    explanation_result: Optional[Dict[str, Any]] = None
    final_result: Optional[Dict[str, Any]] = None
    
    # Derived data (computed once)
    response_times_ms: Optional[List[int]] = None
    likert_responses: Optional[List[int]] = None
    trait_responses: Optional[Dict[str, int]] = None
    
    # HARDENING: Ranking snapshot and checksum
    ranking_snapshot: Optional[RankingSnapshot] = None
    deterministic_checksum: Optional[str] = None
    
    def freeze_answers(self) -> None:
        """Freeze answers for validation. Called once at VALIDATION entry."""
        if self.response_times_ms is None:
            self.response_times_ms = [int(a.response_time_ms) for a in self.answers]
        if self.likert_responses is None:
            self.likert_responses = [
                a.value for a in self.answers 
                if isinstance(a.value, int) and 1 <= a.value <= 7
            ]
        if self.trait_responses is None:
            self.trait_responses = {
                a.question_id: a.value for a in self.answers
                if isinstance(a.value, int)
            }


@dataclass(frozen=True)
class StateTransition:
    """Immutable record of a state transition."""
    from_state: SessionState
    to_state: SessionState
    event: TransitionEvent
    timestamp: float
    metadata: Tuple[Tuple[str, Any], ...] = ()


@dataclass
class Session:
    """
    Complete session with state machine.
    
    INVARIANTS:
        - session_id is immutable after creation
        - current_state is the single source of truth
        - transitions are append-only
        - data modifications follow state rules
    """
    session_id: str
    current_state: SessionState
    data: SessionData
    transitions: List[StateTransition] = field(default_factory=list)
    error_info: Optional[Dict[str, Any]] = None
    
    @property
    def is_terminal(self) -> bool:
        return self.current_state.is_terminal


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE MACHINE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class TransitionError(Exception):
    """Invalid state transition attempt."""
    def __init__(self, current_state: SessionState, event: TransitionEvent, message: str):
        self.current_state = current_state
        self.event = event
        super().__init__(f"TransitionError: {message} [state={current_state.state_name}, event={event.value}]")


class StateMachine:
    """
    Deterministic State Machine for One-Button Flow.
    
    GUARANTEES:
        1. All transitions are atomic
        2. Same (state, event) → same next_state
        3. Invalid transitions raise TransitionError
        4. Terminal states cannot be exited
    
    PRODUCTION HARDENING:
        - ExecutionContext required for SCORING and DECISION
        - Ranking locked after SIMGR scoring
        - Deterministic checksum at RESULT
        - RuleEngine non-reorder guarantee enforced
    """
    
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        # HARDENING: Production hardening controller
        self._hardening = ProductionHardeningController()
        logger.info("StateMachine initialized with PRODUCTION HARDENING")
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Session Management
    # ─────────────────────────────────────────────────────────────────────────
    
    def create_session(self) -> Session:
        """
        Create new session in INIT state.
        
        Returns:
            New Session instance
        """
        session_id = str(uuid.uuid4())
        now = time.time()
        
        session = Session(
            session_id=session_id,
            current_state=SessionState.INIT,
            data=SessionData(session_id=session_id, created_at=now),
            transitions=[],
        )
        
        self._sessions[session_id] = session
        logger.info(f"Session created: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        return self._sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session (cleanup)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
    
    # ─────────────────────────────────────────────────────────────────────────
    #  State Transitions (CORE)
    # ─────────────────────────────────────────────────────────────────────────
    
    def can_transition(self, session: Session, event: TransitionEvent) -> bool:
        """Check if transition is valid."""
        return (session.current_state, event) in TRANSITION_TABLE
    
    def transition(
        self, 
        session: Session, 
        event: TransitionEvent,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionState:
        """
        Execute state transition.
        
        DETERMINISTIC: Same (state, event) → same next_state
        ATOMIC: Either succeeds completely or raises error
        
        Args:
            session: Session to transition
            event: Triggering event
            metadata: Optional transition metadata
        
        Returns:
            New state after transition
        
        Raises:
            TransitionError: If transition is invalid
        """
        current = session.current_state
        key = (current, event)
        
        # Check terminal state
        if current.is_terminal:
            raise TransitionError(current, event, f"Cannot exit terminal state")
        
        # Check valid transition
        if key not in TRANSITION_TABLE:
            valid = VALID_EVENTS.get(current, frozenset())
            raise TransitionError(
                current, event,
                f"Invalid event for state. Valid events: {[e.value for e in valid]}"
            )
        
        # Execute transition
        next_state = TRANSITION_TABLE[key]
        now = time.time()
        
        # Record transition
        transition_record = StateTransition(
            from_state=current,
            to_state=next_state,
            event=event,
            timestamp=now,
            metadata=tuple(sorted(metadata.items())) if metadata else (),
        )
        session.transitions.append(transition_record)
        session.current_state = next_state
        
        logger.debug(f"Transition: {current.state_name} → {next_state.state_name} (event={event.value})")
        return next_state
    
    def force_error(self, session: Session, error_info: Dict[str, Any]) -> SessionState:
        """
        Force transition to ERROR state.
        
        Can be called from any non-terminal state.
        """
        if session.current_state.is_terminal:
            return session.current_state
        
        session.error_info = error_info
        return self.transition(session, TransitionEvent.ERROR_OCCURRED, {"error": error_info})
    
    # ─────────────────────────────────────────────────────────────────────────
    #  State-Specific Actions (NO SIMGRScorer/RuleEngine modification)
    # ─────────────────────────────────────────────────────────────────────────
    
    def execute_validation(self, session: Session) -> Dict[str, Any]:
        """
        Execute VALIDATION state logic.
        
        Uses existing ConsistencyValidator (no modification to scoring).
        """
        from backend.quality.consistency_validator import ConsistencyValidator
        
        assert session.current_state == SessionState.VALIDATION
        
        # Freeze answer data
        session.data.freeze_answers()
        
        # Run validation (quality layer - does NOT affect scoring)
        validator = ConsistencyValidator()
        result = validator.validate(
            response_times_ms=session.data.response_times_ms,
            likert_responses=session.data.likert_responses,
            trait_responses=session.data.trait_responses,
        )
        
        session.data.validation_result = result.to_dict()
        return session.data.validation_result
    
    def execute_scoring(
        self, 
        session: Session,
        scorer,  # SIMGRScorer instance (injected, NOT created)
        context: ExecutionContext,  # REQUIRED: Execution context for security
    ) -> Dict[str, Any]:
        """
        Execute SCORING state logic.
        
        INVARIANT: SIMGRScorer is passed in, NOT modified.
        INVARIANT: Scoring weights are NOT changed.
        INVARIANT: Ranking order is immutable after this method returns.
        
        Args:
            session: Session in SCORING state
            scorer: Pre-configured SIMGRScorer instance
            context: ExecutionContext (REQUIRED by hardening)
        
        Returns:
            Scoring result dict
        
        Raises:
            UnauthorizedScoringAccessError: If context missing or invalid
        """
        assert session.current_state == SessionState.SCORING
        
        # HARDENING: Validate execution context
        if context is None:
            raise UnauthorizedScoringAccessError(
                "ExecutionContext is REQUIRED for scoring",
                context={"session_id": session.session_id},
            )
        context.validate_for_scoring()
        
        # Build input dict from session data
        input_dict = self._build_scoring_input(session)
        
        # Call SIMGRScorer (NO modification - just invoke)
        result = scorer.score(input_dict)
        
        # HARDENING: Lock ranking order immediately after SIMGR returns
        # Ranking order is immutable after SIMGR scoring.
        careers = result.get("careers", [])
        snapshot = self._hardening.lock_ranking(session.session_id, careers)
        session.data.ranking_snapshot = snapshot
        
        session.data.scoring_result = result
        logger.info(
            f"SCORING complete for {session.session_id}: "
            f"{len(careers)} careers, ranking LOCKED"
        )
        return result
    
    def execute_decision(
        self,
        session: Session,
        rule_engine,  # RuleEngine instance (injected, NOT created)
        context: Optional[ExecutionContext] = None,  # Optional but recommended
    ) -> Dict[str, Any]:
        """
        Execute DECISION state logic.
        
        INVARIANT: RuleEngine is passed in, NOT modified.
        INVARIANT: Ranking order is immutable (verified).
        INVARIANT: RuleEngine may NOT reorder, inject, or remove careers.
        
        RuleEngine MAY:
            - Add flags
            - Add warnings
            - Reduce confidence
        
        RuleEngine MAY NOT:
            - Modify career ordering
            - Re-sort results
            - Inject new career
            - Remove existing career
        
        Args:
            session: Session in DECISION state
            rule_engine: Pre-configured RuleEngine instance
            context: ExecutionContext (optional but validated if provided)
        
        Returns:
            Decision result dict
        
        Raises:
            InvariantViolationError: If RuleEngine attempts to reorder
        """
        assert session.current_state == SessionState.DECISION
        
        # HARDENING: Validate context if provided
        if context is not None:
            context.validate_for_decision()
        
        # Build profile from session data
        profile = self._build_profile(session)
        
        # Call RuleEngine (NO modification - just invoke)
        rule_result = rule_engine.process_profile(profile)
        
        # HARDENING: Apply rule result safely (no reordering)
        # This verifies RuleEngine did not reorder, inject, or remove careers
        raw_careers = session.data.scoring_result.get("careers", [])
        final_careers = self._hardening.apply_decision_safely(
            session.session_id,
            raw_careers,
            rule_result,
        )
        
        # Update scoring result with final careers (flags/warnings only)
        session.data.scoring_result["careers"] = final_careers
        session.data.decision_result = rule_result
        
        logger.info(
            f"DECISION complete for {session.session_id}: "
            f"ranking order VERIFIED immutable"
        )
        return rule_result
    
    def execute_explain(self, session: Session) -> Dict[str, Any]:
        """
        Execute EXPLAIN state logic.
        
        Uses existing ExplanationRenderer.
        """
        from backend.quality.explanation_degradation import ExplanationDegradationHandler
        
        assert session.current_state == SessionState.EXPLAIN
        
        # Get confidence from validation
        confidence = session.data.validation_result.get("confidence_score", 1.0)
        
        # Build explanation (quality layer - does NOT affect scoring)
        handler = ExplanationDegradationHandler()
        explanation = handler.build_explanation(
            scoring_result=session.data.scoring_result,
            decision_result=session.data.decision_result,
            confidence=confidence,
        )
        
        session.data.explanation_result = explanation
        return explanation
    
    def build_final_result(self, session: Session) -> Dict[str, Any]:
        """
        Build final result from all stages.
        
        Called at RESULT state entry.
        
        HARDENING: Generates and stores deterministic checksum.
        Same input → same output → same checksum (INVARIANT).
        """
        assert session.current_state == SessionState.RESULT
        
        # Get final careers (with flags/warnings applied)
        final_careers = session.data.scoring_result.get("careers", [])
        
        # HARDENING: Generate deterministic checksum
        checksum = self._hardening.generate_and_verify_checksum(
            session.session_id,
            final_careers,
        )
        session.data.deterministic_checksum = checksum
        
        session.data.final_result = {
            "session_id": session.session_id,
            "status": "completed",
            "scoring": session.data.scoring_result,
            "decision": session.data.decision_result,
            "explanation": session.data.explanation_result,
            "confidence": session.data.validation_result.get("confidence_score", 1.0),
            "quality_flags": session.data.validation_result.get("breakdown", {}),
            # HARDENING: Include checksum for verification
            "checksum": checksum,
        }
        
        logger.info(
            f"RESULT built for {session.session_id}: checksum={checksum[:16]}..."
        )
        return session.data.final_result
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Helper Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    def _build_scoring_input(self, session: Session) -> Dict[str, Any]:
        """Build SIMGRScorer input from session data."""
        # Convert answers to user profile format
        return {
            "user": session.data.user_profile or {},
            "careers": [],  # Populated by external data
        }
    
    def _build_profile(self, session: Session) -> Dict[str, Any]:
        """Build RuleEngine profile from session data."""
        return session.data.user_profile or {}


# ═══════════════════════════════════════════════════════════════════════════════
#  SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

_state_machine: Optional[StateMachine] = None


def get_state_machine() -> StateMachine:
    """Get global state machine instance."""
    global _state_machine
    if _state_machine is None:
        _state_machine = StateMachine()
    return _state_machine
