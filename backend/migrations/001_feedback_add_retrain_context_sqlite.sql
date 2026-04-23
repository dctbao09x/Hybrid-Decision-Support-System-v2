-- ==============================================================================
-- Migration: feedback_add_retrain_context (SQLite version)
-- Date: 2026-02-20
-- Description: Add retrain-grade context fields to feedback table
-- ==============================================================================

-- SQLite doesn't support ADD COLUMN IF NOT EXISTS, so we use a different approach

-- Add new columns for retrain-grade data
-- Note: SQLite requires separate ALTER statements
ALTER TABLE feedback ADD COLUMN career_id TEXT DEFAULT '';
ALTER TABLE feedback ADD COLUMN rank_position INTEGER DEFAULT 0;
ALTER TABLE feedback ADD COLUMN score_snapshot TEXT DEFAULT '{}';
ALTER TABLE feedback ADD COLUMN profile_snapshot TEXT DEFAULT '{}';
ALTER TABLE feedback ADD COLUMN model_version TEXT DEFAULT '';
ALTER TABLE feedback ADD COLUMN kb_version TEXT DEFAULT NULL;
ALTER TABLE feedback ADD COLUMN confidence REAL DEFAULT NULL;
ALTER TABLE feedback ADD COLUMN explicit_accept INTEGER DEFAULT NULL;
ALTER TABLE feedback ADD COLUMN session_id TEXT DEFAULT NULL;

-- Add indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_feedback_career_id ON feedback(career_id);
CREATE INDEX IF NOT EXISTS idx_feedback_model_version ON feedback(model_version);
CREATE INDEX IF NOT EXISTS idx_feedback_training_accept ON feedback(training_status, explicit_accept);
CREATE INDEX IF NOT EXISTS idx_feedback_explicit_accept ON feedback(explicit_accept);
CREATE INDEX IF NOT EXISTS idx_feedback_career_model ON feedback(career_id, model_version);

-- ==============================================================================
-- VERIFICATION
-- ==============================================================================

-- Verify columns exist
-- PRAGMA table_info(feedback);
