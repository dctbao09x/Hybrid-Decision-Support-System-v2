# backend/flow/__init__.py
"""
One-Button Flow Module
======================

Deterministic state machine for career assessment flow.

Components:
    - state_machine: Core state machine engine
    - api_contract: API endpoint definitions with JSON schemas
    - failure_policy: Error handling and recovery
    - invariants: Production hardening enforcement (NEW)

ARCHITECTURE COMPLIANCE:
    - NO modification to SIMGRScorer
    - NO modification to RuleEngine
    - NO change in scoring weights
    - NO chat-style API
    - ALL decisions local deterministic

PRODUCTION HARDENING (2026-02-21):
    - I.   RANKING_IMMUTABILITY: Ranking locked after SIMGR scoring
    - II.  DETERMINISTIC_CHECKSUM: SHA256 output verification
    - III. ANTI_BYPASS: ExecutionContext required for scoring
    - IV.  STRICT_SCHEMA: No implicit type coercion
    - V.   NON_REORDER_GUARANTEE: RuleEngine cannot reorder careers
"""

from backend.flow.state_machine import (
    SessionState,
    TransitionEvent,
    Session,
    SessionData,
    AssessmentAnswer,
    StateMachine,
    TransitionError,
    get_state_machine,
    TRANSITION_TABLE,
    VALID_EVENTS,
)

from backend.flow.invariants import (
    # Error Types
    InvariantViolationType,
    InvariantViolationError,
    UnauthorizedScoringAccessError,
    DeterministicInvarianceError,
    RankingOrderViolationError,
    # Ranking Immutability
    RankingSnapshot,
    RankingImmutabilityEnforcer,
    # Deterministic Checksum
    DeterministicChecksum,
    DeterministicOutputValidator,
    # Execution Context
    ExecutionContext,
    create_execution_context,
    require_execution_context,
    # Guards
    StateTransitionGuard,
    RuleEngineGuard,
    # Combined Controller
    ProductionHardeningController,
)

__all__ = [
    # State Machine
    "SessionState",
    "TransitionEvent",
    "Session",
    "SessionData",
    "AssessmentAnswer",
    "StateMachine",
    "TransitionError",
    "get_state_machine",
    "TRANSITION_TABLE",
    "VALID_EVENTS",
    # Invariants (Hardening)
    "InvariantViolationType",
    "InvariantViolationError",
    "UnauthorizedScoringAccessError",
    "DeterministicInvarianceError",
    "RankingOrderViolationError",
    "RankingSnapshot",
    "RankingImmutabilityEnforcer",
    "DeterministicChecksum",
    "DeterministicOutputValidator",
    "ExecutionContext",
    "create_execution_context",
    "require_execution_context",
    "StateTransitionGuard",
    "RuleEngineGuard",
    "ProductionHardeningController",
]
