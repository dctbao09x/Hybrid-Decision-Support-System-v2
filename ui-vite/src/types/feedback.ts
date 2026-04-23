// src/types/feedback.ts
/**
 * Feedback Types (Stage 7)
 * 
 * Types for closed-loop feedback system.
 * All feedback MUST have trace_id - no orphan feedback allowed.
 */

/**
 * Feedback sources
 */
export type FeedbackSource = 'analyze' | 'recommend' | 'chat';

/**
 * Feedback status from backend
 */
export type FeedbackStatus = 'pending' | 'approved' | 'rejected' | 'flagged';

/**
 * Trace metadata injected into all API responses
 */
export interface TraceMeta {
  trace_id: string;
  model_version: string;
  kb_version: string;
  confidence: number;
}

/**
 * Correction data submitted by user
 */
export interface FeedbackCorrection {
  correct_career?: string;
  skill_adjustments?: Record<string, number>;
  additional_context?: string;
}

/**
 * Score snapshot at feedback time
 */
export interface ScoreSnapshot {
  matchScore: number;
  studyScore?: number;
  interestScore?: number;
  marketScore?: number;
  growthScore?: number;
  riskScore?: number;
  [key: string]: number | undefined;
}

/**
 * Feedback submission request
 * 
 * RETRAIN-GRADE REQUIREMENTS (2026-02-20):
 * All fields marked REQUIRED must be provided.
 * Missing fields will result in HTTP 422.
 */
export interface FeedbackSubmitRequest {
  // === EXISTING FIELDS ===
  trace_id: string;
  rating: number;  // 1-5
  correction: FeedbackCorrection;
  reason: string;
  source: FeedbackSource;
  user_id?: string;
  
  // === RETRAIN-GRADE REQUIRED FIELDS ===
  career_id: string;           // REQUIRED: Career being rated
  rank_position: number;       // REQUIRED: Rank at feedback time (1-indexed)
  score_snapshot: ScoreSnapshot; // REQUIRED: Scores at feedback time (must include matchScore)
  profile_snapshot: Record<string, unknown>; // REQUIRED: User profile snapshot
  model_version: string;       // REQUIRED: Model version used
  explicit_accept: boolean;    // REQUIRED: True if rating >= 4, False if rating <= 2
  
  // === OPTIONAL FIELDS ===
  kb_version?: string;
  confidence?: number;
  session_id?: string;
}

/**
 * Feedback submission response
 */
export interface FeedbackSubmitResponse {
  feedback_id: string;
  trace_id: string;
  status: string;
  message: string;
}

/**
 * Feedback detail response
 */
export interface FeedbackDetailResponse {
  feedback_id: string;
  trace_id: string;
  rating: number;
  correction: FeedbackCorrection;
  reason: string;
  source?: FeedbackSource;
  status: FeedbackStatus;
  created_at: string;
  reviewed_at?: string;
  reviewer_id?: string;
  review_notes?: string;
  linked_train_id?: string;
  quality_score: number;
}

/**
 * Feedback list response
 */
export interface FeedbackListResponse {
  items: FeedbackDetailResponse[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Feedback statistics response
 */
export interface FeedbackStatsResponse {
  total_feedback: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  flagged_count: number;
  feedback_rate: number;
  approval_rate: number;
  correction_rate: number;
  avg_rating: number;
  avg_quality_score: number;
  training_samples_generated: number;
  training_samples_used: number;
  retrain_impact: number;
  drift_signal: number;
  career_distribution: Record<string, number>;
  // Admin dashboard fields
  linked_to_trace?: number;
  pending_for_training?: number;
  status_counts?: {
    pending: number;
    approved: number;
    rejected: number;
    used_in_training: number;
  };
  source_distribution?: Record<FeedbackSource, number>;
}

/**
 * Feedback item for list display
 */
export interface FeedbackItem {
  feedback_id: string;
  trace_id: string;
  rating: number;
  correction: FeedbackCorrection;
  reason: string;
  source: FeedbackSource;
  status: string;
  created_at: string;
  reviewed_at?: string;
}

/**
 * Feedback list request parameters
 */
export interface FeedbackListRequest {
  status?: string;
  source?: FeedbackSource;
  from_date?: string;
  to_date?: string;
  limit: number;
  offset: number;
}

/**
 * Feedback panel state machine
 */
export type FeedbackPanelState = 'idle' | 'shown' | 'submitted' | 'locked';

/**
 * Session feedback state
 */
export interface FeedbackSessionState {
  trace_id: string;
  state: FeedbackPanelState;
  submitted_at?: string;
  feedback_id?: string;
}

/**
 * Feedback form data (local)
 */
export interface FeedbackFormData {
  rating: number;
  correction: string;  // Will be parsed into FeedbackCorrection
  reason: string;
}

/**
 * Validation result
 */
export interface FeedbackValidation {
  valid: boolean;
  errors: {
    rating?: string;
    correction?: string;
    reason?: string;
  };
}

/**
 * Auto-trigger policy configuration
 */
export interface FeedbackTriggerPolicy {
  lowConfidenceThreshold: number;  // Show if confidence < threshold
  scrollEndTrigger: boolean;
  sessionEndTrigger: boolean;
  minTimeBeforeShow: number;  // ms
}

/**
 * Default trigger policy
 */
export const DEFAULT_TRIGGER_POLICY: FeedbackTriggerPolicy = {
  lowConfidenceThreshold: 0.8,
  scrollEndTrigger: true,
  sessionEndTrigger: true,
  minTimeBeforeShow: 3000,  // 3 seconds
};
