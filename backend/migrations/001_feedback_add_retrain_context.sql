-- ==============================================================================
-- Migration: feedback_add_retrain_context
-- Date: 2026-02-20
-- Description: Add retrain-grade context fields to feedback table
-- ==============================================================================

-- ==============================================================================
-- FORWARD MIGRATION (UP)
-- ==============================================================================

-- Add new columns for retrain-grade data
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS career_id VARCHAR(64);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS rank_position INT DEFAULT 0;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS score_snapshot JSONB DEFAULT '{}';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS profile_snapshot JSONB DEFAULT '{}';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS model_version VARCHAR(32);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS kb_version VARCHAR(32);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS confidence FLOAT;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS explicit_accept BOOLEAN;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS session_id VARCHAR(64);

-- Add indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_feedback_career_id ON feedback(career_id);
CREATE INDEX IF NOT EXISTS idx_feedback_model_version ON feedback(model_version);
CREATE INDEX IF NOT EXISTS idx_feedback_training_accept ON feedback(training_status, explicit_accept);
CREATE INDEX IF NOT EXISTS idx_feedback_explicit_accept ON feedback(explicit_accept);

-- Composite index for common admin queries
CREATE INDEX IF NOT EXISTS idx_feedback_career_model ON feedback(career_id, model_version);

-- Add comments for documentation
COMMENT ON COLUMN feedback.career_id IS 'Career ID being rated - REQUIRED for retrain';
COMMENT ON COLUMN feedback.rank_position IS 'Rank position at feedback time (1-indexed) - REQUIRED for retrain';
COMMENT ON COLUMN feedback.score_snapshot IS 'Score snapshot at feedback time (JSON) - REQUIRED for retrain';
COMMENT ON COLUMN feedback.profile_snapshot IS 'User profile snapshot (JSON) - REQUIRED for retrain';
COMMENT ON COLUMN feedback.model_version IS 'Model version used for prediction - REQUIRED for retrain';
COMMENT ON COLUMN feedback.kb_version IS 'Knowledge base version used';
COMMENT ON COLUMN feedback.confidence IS 'Model confidence score (0-1)';
COMMENT ON COLUMN feedback.explicit_accept IS 'True = accept (rating >= 4), False = reject (rating <= 2)';
COMMENT ON COLUMN feedback.session_id IS 'Session ID for tracking';

-- ==============================================================================
-- VERIFICATION QUERIES
-- ==============================================================================

-- Verify columns exist
-- SELECT column_name, data_type, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_name = 'feedback' 
-- AND column_name IN ('career_id', 'rank_position', 'score_snapshot', 'profile_snapshot', 'model_version');

-- Verify indexes exist
-- SELECT indexname FROM pg_indexes WHERE tablename = 'feedback';
