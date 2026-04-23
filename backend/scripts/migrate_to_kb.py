# backend/scripts/migrate_to_kb.py
"""
Knowledge Base Migration Tool

Purpose:
- Reset database
- Seed initial career data
- Migrate legacy datasets

Usage:
    python migrate_to_kb.py
    python migrate_to_kb.py --force
    python migrate_to_kb.py --dry-run
"""

import sys
import argparse
import logging
from pathlib import Path


# =====================================================
# PATH SETUP
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("kb-migration")


# =====================================================
# IMPORTS
# =====================================================

from backend.kb.database import reset_db
from backend.kb.seed import seed_all


# =====================================================
# ARGUMENT PARSER
# =====================================================

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Knowledge Base Migration Tool"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without modifying database",
    )

    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Reset DB without importing data",
    )

    return parser.parse_args()


# =====================================================
# CORE MIGRATION
# =====================================================

def migrate(force: bool, dry_run: bool, no_seed: bool) -> int:
    """
    Run migration process

    Returns:
        Exit code (0 = success)
    """

    logger.info("Starting Knowledge Base migration")

    if dry_run:
        logger.warning("DRY RUN MODE - No data will be modified")

    # ---------- Confirmation ----------

    if not force and not dry_run:

        answer = input(
            "This will RESET the database. Continue? (yes/no): "
        ).strip().lower()

        if answer != "yes":
            logger.warning("Migration cancelled by user")
            return 1

    # ---------- Reset ----------

    if dry_run:
        logger.info("[DRY-RUN] Would reset database")
    else:
        logger.info("Resetting database...")
        reset_db(confirm=True)
        logger.info("Database reset complete")

    # ---------- Seeding ----------

    if no_seed:
        logger.info("Skipping seed phase (--no-seed enabled)")
        return 0

    if dry_run:
        logger.info("[DRY-RUN] Would seed initial data")
    else:
        logger.info("Seeding Knowledge Base...")
        seed_all()
        logger.info("Seed completed")

    logger.info("Migration finished successfully")

    return 0


# =====================================================
# ENTRY POINT
# =====================================================

def main():

    args = parse_args()

    exit_code = migrate(
        force=args.force,
        dry_run=args.dry_run,
        no_seed=args.no_seed,
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
