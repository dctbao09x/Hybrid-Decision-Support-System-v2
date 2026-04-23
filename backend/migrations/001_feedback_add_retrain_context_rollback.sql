-- ==============================================================================
-- Migration: feedback_add_retrain_context (ROLLBACK)
-- Date: 2026-02-20
-- Description: Rollback retrain-grade context fields from feedback table
-- WARNING: This will DROP columns and their data!
-- ==============================================================================

-- ==============================================================================
-- REVERSE MIGRATION (DOWN)
-- ==============================================================================

-- Drop indexes first
DROP INDEX IF EXISTS idx_feedback_career_id;
DROP INDEX IF EXISTS idx_feedback_model_version;
DROP INDEX IF EXISTS idx_feedback_training_accept;
DROP INDEX IF EXISTS idx_feedback_explicit_accept;
DROP INDEX IF EXISTS idx_feedback_career_model;

-- Drop columns (WARNING: Data loss!)
ALTER TABLE feedback DROP COLUMN IF EXISTS career_id;
ALTER TABLE feedback DROP COLUMN IF EXISTS rank_position;
ALTER TABLE feedback DROP COLUMN IF EXISTS score_snapshot;
ALTER TABLE feedback DROP COLUMN IF EXISTS profile_snapshot;
ALTER TABLE feedback DROP COLUMN IF EXISTS model_version;
ALTER TABLE feedback DROP COLUMN IF EXISTS kb_version;
ALTER TABLE feedback DROP COLUMN IF EXISTS confidence;
ALTER TABLE feedback DROP COLUMN IF EXISTS explicit_accept;
ALTER TABLE feedback DROP COLUMN IF EXISTS session_id;

-- ==============================================================================
-- VERIFICATION
-- ==============================================================================

-- Verify columns are removed
-- SELECT column_name 
-- FROM information_schema.columns 
-- WHERE table_name = 'feedback';
