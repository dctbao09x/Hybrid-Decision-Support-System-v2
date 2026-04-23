#!/usr/bin/env python
"""
Runtime Log Capture - BASELINE FREEZE
Runs full scoring flow with DEBUG logging.
"""
import sys
sys.path.insert(0, '.')

import logging
import json
from datetime import datetime

# Set DEBUG level for all scoring modules
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('baseline/baseline_runtime.log', mode='w'),
        logging.StreamHandler()
    ]
)

# Enable debug for scoring-related modules
for name in ['backend.scoring', 'backend.scoring.engine', 'backend.scoring.config', 
             'backend.scoring.config_loader', 'backend.scoring.components',
             'backend.scoring.scorer', 'backend.scoring.strategies']:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

root_logger = logging.getLogger()
root_logger.info("=" * 80)
root_logger.info("BASELINE RUNTIME LOG CAPTURE")
root_logger.info(f"Timestamp: {datetime.now().isoformat()}")
root_logger.info("=" * 80)

# Import scoring modules
root_logger.info("PHASE 1: Loading scoring modules...")

try:
    from backend.scoring.config import SIMGRWeights
    root_logger.info(f"Loaded SIMGRWeights from backend.scoring.config")
    
    from backend.scoring.config_loader import ScoringConfigLoader
    root_logger.info(f"Loaded ScoringConfigLoader")
    
    # Load config
    loader = ScoringConfigLoader()
    config = loader.load()
    root_logger.info(f"Config loaded from: {config._source}")
    root_logger.info(f"SIMGR Weights: S={config.simgr_weights.study_score}, "
                    f"I={config.simgr_weights.interest_score}, "
                    f"M={config.simgr_weights.market_score}, "
                    f"G={config.simgr_weights.growth_score}, "
                    f"R={config.simgr_weights.risk_score}")
    
except Exception as e:
    root_logger.error(f"Failed to load config: {e}")
    raise

# Load weights
root_logger.info("PHASE 2: Loading weights...")
try:
    weights = SIMGRWeights.from_file()
    root_logger.info(f"Weights loaded: source={weights._source}, version={weights._version}")
except Exception as e:
    root_logger.error(f"Failed to load weights: {e}")

# Load scorer
root_logger.info("PHASE 3: Loading scorer...")
try:
    from backend.scoring.scorer import SIMGRScorer
    scorer = SIMGRScorer()
    root_logger.info(f"SIMGRScorer initialized")
except Exception as e:
    root_logger.error(f"Failed to init scorer: {e}")

# Load ranking engine
root_logger.info("PHASE 4: Loading ranking engine...")
try:
    from backend.scoring.engine import RankingEngine
    engine = RankingEngine()
    root_logger.info(f"RankingEngine initialized")
except Exception as e:
    root_logger.error(f"Failed to init engine: {e}")

# Test input
root_logger.info("PHASE 5: Running test scoring...")
test_input = {
    "user_id": "baseline_test_001",
    "skills": ["Python", "Machine Learning", "Data Science"],
    "interests": ["AI", "Software Development"],
    "experience_years": 3,
    "education_level": "Bachelor"
}
root_logger.info(f"Test input: {json.dumps(test_input)}")

try:
    # Run scoring
    from backend.scoring.engine import RankingEngine
    from backend.scoring.models import UserProfile, CareerData
    
    engine = RankingEngine()
    
    # Create UserProfile (no user_id field in model)
    user = UserProfile(
        skills=test_input["skills"],
        interests=test_input["interests"],
    )
    root_logger.info(f"Created UserProfile: skills={user.skills}")
    
    # Create CareerData objects (check model schema)
    careers = [
        CareerData(name="Software Engineer", domain="it", required_skills=["Python", "Git"]),
        CareerData(name="Data Scientist", domain="it", required_skills=["Python", "Machine Learning"]),
        CareerData(name="ML Engineer", domain="it", required_skills=["Python", "Deep Learning"]),
        CareerData(name="DevOps Engineer", domain="it", required_skills=["Docker", "Kubernetes"]),
        CareerData(name="Product Manager", domain="business", required_skills=["Communication"]),
    ]
    root_logger.info(f"Using {len(careers)} CareerData objects for scoring")
    
    # Run ranking
    results = engine.rank(
        user=user,
        careers=careers,
    )
    
    root_logger.info(f"Scoring complete. Results: {len(results)} careers ranked")
    for i, r in enumerate(results[:3]):
        root_logger.info(f"  #{i+1}: {r.career_name} = {r.total_score:.4f}")
        
except Exception as e:
    root_logger.error(f"Scoring failed: {e}")
    import traceback
    root_logger.error(traceback.format_exc())

root_logger.info("=" * 80)
root_logger.info("RUNTIME LOG CAPTURE COMPLETE")
root_logger.info("=" * 80)

print("\nRuntime log saved to: baseline/baseline_runtime.log")
