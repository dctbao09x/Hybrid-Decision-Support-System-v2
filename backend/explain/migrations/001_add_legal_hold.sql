-- Migration Script: Add legal_hold column to explanations table
-- Version: 2026.02.14.001
-- Purpose: Support legal hold functionality for retention management

-- SQLite migration (for existing databases)
-- Run this script manually if automatic migration fails

-- Step 1: Add legal_hold column (if not exists)
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE
-- This will fail silently if column already exists
ALTER TABLE explanations ADD COLUMN legal_hold INTEGER DEFAULT 0;

-- Step 2: Create index for performance
CREATE INDEX IF NOT EXISTS idx_expl_legal_hold ON explanations(legal_hold);

-- Step 3: Verify migration
SELECT COUNT(*) as total_records,
       SUM(legal_hold) as records_on_hold
FROM explanations
WHERE is_deleted = 0;

-- Migration complete
-- Note: The Python code in storage.py handles this migration automatically
-- on startup. This script is provided for manual intervention if needed.
