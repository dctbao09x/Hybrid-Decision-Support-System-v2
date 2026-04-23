# backend/scripts/test_kb.py
"""
Knowledge Base Integration Test Suite
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Any

# ----------------------------
# Path bootstrap
# ----------------------------

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ----------------------------
# Logging
# ----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | kb-test | %(message)s",
)

logger = logging.getLogger("kb-test")


# ----------------------------
# Imports
# ----------------------------

from backend.kb.database import get_db_context
from backend.kb.service import KnowledgeBaseService
from backend.rule_engine.adapters.kb_adapter import kb_adapter


# ============================================================
# SERVICE LAYER TEST
# ============================================================

def test_service_layer() -> None:
    """Test KnowledgeBaseService"""

    logger.info("Testing Service Layer")

    with get_db_context() as db:

        kb = KnowledgeBaseService(db)

        # ----------------------------
        # 1. Get career
        # ----------------------------

        career_name = "AI Engineer"

        career = kb.get_career_by_name(career_name)

        assert career is not None, f"Career not found: {career_name}"

        assert career.domain is not None, "Career missing domain"
        assert career.name == career_name

        logger.info("✓ Found career: %s", career.name)
        logger.info("  Domain: %s", career.domain.name)
        logger.info("  Skills: %d", len(career.career_skills))
        logger.info("  Roadmaps: %d", len(career.roadmaps))

        # ----------------------------
        # 2. List careers
        # ----------------------------

        careers = kb.list_careers(limit=5)

        assert len(careers) > 0, "No careers returned"

        logger.info("✓ list_careers returned %d records", len(careers))

        for c in careers:
            assert c.name
            assert c.domain
            logger.info("  - %s (%s)", c.name, c.domain.name)

        # ----------------------------
        # 3. Filters
        # ----------------------------

        from kb.schemas import CareerFilter

        filtered = kb.list_careers(
            filters=CareerFilter(min_ai_relevance=0.8)
        )

        assert isinstance(filtered, list)

        logger.info(
            "✓ Filtered AI careers: %d",
            len(filtered)
        )


# ============================================================
# ADAPTER TEST
# ============================================================

def test_adapter() -> None:
    """Test KB Adapter"""

    logger.info("Testing KB Adapter")

    # ----------------------------
    # 1. get_job_requirements
    # ----------------------------

    job_name = "Data Scientist"

    reqs: Dict[str, Any] = kb_adapter.get_job_requirements(job_name)

    assert isinstance(reqs, dict)
    assert "domain" in reqs
    assert "required_skills" in reqs

    logger.info("✓ Requirements for %s loaded", job_name)
    logger.info("  Domain: %s", reqs.get("domain"))
    logger.info("  Required skills: %d", len(reqs.get("required_skills", [])))
    logger.info("  AI relevance: %s", reqs.get("ai_relevance"))

    # ----------------------------
    # 2. get_all_jobs
    # ----------------------------

    jobs = kb_adapter.get_all_jobs()

    assert isinstance(jobs, list)
    assert len(jobs) > 0

    logger.info("✓ Total jobs: %d", len(jobs))
    logger.info("  First 3: %s", jobs[:3])

    # ----------------------------
    # 3. Education hierarchy
    # ----------------------------

    hierarchy = kb_adapter.get_education_hierarchy()

    assert isinstance(hierarchy, dict)
    assert "Bachelor" in hierarchy

    logger.info("✓ Education levels: %d", len(hierarchy))
    logger.info("  Bachelor level: %s", hierarchy.get("Bachelor"))

    # ----------------------------
    # 4. Domain interest map
    # ----------------------------

    domain_map = kb_adapter.get_domain_interest_map()

    assert isinstance(domain_map, dict)

    logger.info("✓ Domain map loaded: %d domains", len(domain_map))
    logger.info("  AI interests: %s", domain_map.get("AI", []))


# ============================================================
# RULE ENGINE TEST
# ============================================================

def test_rule_engine() -> None:
    """Test Rule Engine Integration"""

    logger.info("Testing Rule Engine")

    from rule_engine.rule_engine import RuleEngine

    # ----------------------------
    # 1. Init
    # ----------------------------

    engine = RuleEngine()

    assert engine.rules
    assert len(engine.rules) > 0

    logger.info("✓ Loaded %d rules", len(engine.rules))

    # ----------------------------
    # 2. Evaluation
    # ----------------------------

    test_profile = {
        "age": 22,
        "education_level": "Bachelor",
        "interest_tags": ["IT", "Artificial Intelligence"],
        "skill_tags": ["Python", "Machine Learning"],
        "intent": "career_intent",
        "confidence_score": 0.85,
        "similarity_scores": {
            "AI Engineer": 0.92,
            "Data Scientist": 0.85
        }
    }

    result = engine.evaluate_job(
        test_profile,
        "AI Engineer"
    )

    assert result is not None
    assert "passed" in result
    assert "score_delta" in result
    assert "flags" in result

    logger.info("✓ Rule evaluation OK")
    logger.info("  Passed: %s", result["passed"])
    logger.info("  Score delta: %s", result["score_delta"])
    logger.info("  Flags: %d", len(result["flags"]))


# ============================================================
# RUNNER
# ============================================================

def run_all_tests() -> int:
    """Run full test suite"""

    logger.info("=" * 70)
    logger.info("START KNOWLEDGE BASE TEST SUITE")
    logger.info("=" * 70)

    try:

        test_service_layer()
        test_adapter()
        test_rule_engine()

        logger.info("=" * 70)
        logger.info("ALL TESTS PASSED")
        logger.info("=" * 70)

        return 0

    except AssertionError as e:

        logger.error("ASSERTION FAILED: %s", e)
        return 1

    except Exception as e:

        logger.exception("UNEXPECTED ERROR: %s", e)
        return 2


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    exit_code = run_all_tests()
    sys.exit(exit_code)
