// src/store/feedbackStore.ts
/**
 * Feedback Store (Stage 7)
 * 
 * State management for feedback panel.
 * Persists state per session (sessionStorage only - no PII in localStorage).
 * 
 * State Machine: idle → shown → submitted → locked
 */

import type {
  FeedbackPanelState,
  FeedbackSessionState,
  FeedbackTriggerPolicy,
} from '../types/feedback';
import { logDebug, logWarn, logError } from '../utils/logger';

// Session storage key (no PII stored)
const SESSION_KEY = 'feedback_session_state';

// In-memory state for current session
let currentState: Map<string, FeedbackSessionState> = new Map();

/**
 * Initialize store from session storage.
 */
function initStore(): void {
  try {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored) {
      const data = JSON.parse(stored) as Record<string, FeedbackSessionState>;
      currentState = new Map(Object.entries(data));
    }
  } catch (err) {
    logWarn('[FeedbackStore] Failed to load state', { error: String(err) });
    currentState = new Map();
  }
}

/**
 * Persist state to session storage.
 * Only stores trace_id and state - no PII.
 */
function persistStore(): void {
  try {
    const data: Record<string, FeedbackSessionState> = {};
    for (const [key, value] of currentState.entries()) {
      // Only persist non-PII fields
      data[key] = {
        trace_id: value.trace_id,
        state: value.state,
        submitted_at: value.submitted_at,
        feedback_id: value.feedback_id,
      };
    }
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
  } catch (err) {
    logWarn('[FeedbackStore] Failed to persist state', { error: String(err) });
  }
}

// Initialize on module load
initStore();

// ==============================================================================
// State Change Listeners (defined before state modification functions)
// ==============================================================================

/**
 * Subscribe to state changes (for components).
 */
type StateListener = (traceId: string, newState: FeedbackPanelState) => void;
const listeners: StateListener[] = [];

export function subscribeToStateChanges(listener: StateListener): () => void {
  listeners.push(listener);
  return () => {
    const index = listeners.indexOf(listener);
    if (index > -1) {
      listeners.splice(index, 1);
    }
  };
}

function notifyListeners(traceId: string, newState: FeedbackPanelState): void {
  for (const listener of listeners) {
    try {
      listener(traceId, newState);
    } catch (err) {
      logError('[FeedbackStore] Listener error', { error: String(err) });
    }
  }
}

// ==============================================================================
// State Getters
// ==============================================================================

/**
 * Get feedback state for a trace.
 */
export function getFeedbackState(traceId: string): FeedbackSessionState | undefined {
  return currentState.get(traceId);
}

/**
 * Get current panel state for a trace.
 */
export function getPanelState(traceId: string): FeedbackPanelState {
  return currentState.get(traceId)?.state || 'idle';
}

/**
 * Check if feedback is locked (already submitted).
 */
export function isFeedbackLocked(traceId: string): boolean {
  const state = getPanelState(traceId);
  return state === 'submitted' || state === 'locked';
}

/**
 * Check if feedback can be shown.
 */
export function canShowFeedback(traceId: string): boolean {
  if (!traceId) return false;
  const state = getPanelState(traceId);
  return state === 'idle' || state === 'shown';
}

/**
 * Transition to 'shown' state.
 */
export function showFeedback(traceId: string): boolean {
  if (!traceId) return false;
  
  const current = getPanelState(traceId);
  if (current === 'submitted' || current === 'locked') {
    logDebug('[FeedbackStore] Cannot show - already submitted/locked', { traceId });
    return false;
  }
  
  currentState.set(traceId, {
    trace_id: traceId,
    state: 'shown',
  });
  persistStore();
  notifyListeners(traceId, 'shown');
  
  logDebug('[FeedbackStore] State changed', { traceId, transition: 'idle → shown' });
  return true;
}

/**
 * Transition to 'submitted' state.
 */
export function markSubmitted(traceId: string, feedbackId: string): boolean {
  if (!traceId) return false;
  
  const current = getPanelState(traceId);
  if (current === 'submitted' || current === 'locked') {
    logDebug('[FeedbackStore] Already submitted/locked', { traceId });
    return false;
  }
  
  currentState.set(traceId, {
    trace_id: traceId,
    state: 'submitted',
    submitted_at: new Date().toISOString(),
    feedback_id: feedbackId,
  });
  persistStore();
  notifyListeners(traceId, 'submitted');
  
  logDebug('[FeedbackStore] State changed', { traceId, transition: `${current} → submitted` });
  return true;
}

/**
 * Transition to 'locked' state.
 * Called after successful submission confirmation.
 */
export function lockFeedback(traceId: string): boolean {
  const state = currentState.get(traceId);
  if (!state) return false;
  
  state.state = 'locked';
  persistStore();
  notifyListeners(traceId, 'locked');
  
  logDebug('[FeedbackStore] State changed', { traceId, transition: 'submitted → locked' });
  return true;
}

/**
 * Reset feedback state (admin only, for testing).
 */
export function resetFeedbackState(traceId: string): void {
  currentState.delete(traceId);
  persistStore();
  logDebug('[FeedbackStore] State reset', { traceId });
}

/**
 * Clear all feedback states.
 */
export function clearAllFeedbackStates(): void {
  currentState.clear();
  sessionStorage.removeItem(SESSION_KEY);
  logDebug('[FeedbackStore] All states cleared');
}

/**
 * Get all submitted feedback IDs in session.
 */
export function getSubmittedFeedbackIds(): string[] {
  const ids: string[] = [];
  for (const state of currentState.values()) {
    if (state.state === 'submitted' || state.state === 'locked') {
      if (state.feedback_id) {
        ids.push(state.feedback_id);
      }
    }
  }
  return ids;
}

/**
 * Calculate session feedback rate.
 */
export function getSessionFeedbackRate(): { submitted: number; total: number; rate: number } {
  const total = currentState.size;
  const submitted = Array.from(currentState.values())
    .filter(s => s.state === 'submitted' || s.state === 'locked')
    .length;
  
  return {
    submitted,
    total,
    rate: total > 0 ? submitted / total : 0,
  };
}

// ==============================================================================
// AUTO-TRIGGER POLICY
// ==============================================================================

/**
 * Evaluate auto-trigger policy.
 */
export function shouldAutoShowFeedback(
  traceId: string,
  confidence: number,
  policy: FeedbackTriggerPolicy = {
    lowConfidenceThreshold: 0.8,
    scrollEndTrigger: true,
    sessionEndTrigger: true,
    minTimeBeforeShow: 3000,
  }
): boolean {
  // Don't show if already submitted/locked
  if (isFeedbackLocked(traceId)) {
    return false;
  }
  
  // Trigger on low confidence
  if (confidence < policy.lowConfidenceThreshold) {
    logDebug('[FeedbackStore] Auto-trigger: low confidence', { confidence });
    return true;
  }
  
  return false;
}
