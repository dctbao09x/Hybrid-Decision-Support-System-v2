#!/usr/bin/env python
"""
Config Snapshot Script - BASELINE FREEZE
"""
import sys
sys.path.insert(0, '.')

import json
import yaml
import os
from dataclasses import asdict
from pathlib import Path

result = {}

# 1. weights from models/weights/active/weights.json
if os.path.exists('models/weights/active/weights.json'):
    with open('models/weights/active/weights.json') as f:
        result['active_weights'] = json.load(f)
else:
    result['active_weights'] = 'NOT FOUND'

# 2. config/scoring.yaml
if os.path.exists('config/scoring.yaml'):
    with open('config/scoring.yaml', encoding='utf-8') as f:
        result['scoring_yaml'] = yaml.safe_load(f)
else:
    result['scoring_yaml'] = 'NOT FOUND'

# 3. env variables related to scoring
env_keys = [k for k in os.environ if 'SCOR' in k.upper() or 'WEIGHT' in k.upper() or 'SIMGR' in k.upper()]
result['env_variables'] = {k: os.environ[k] for k in env_keys}

# 4. Override flags
override_path = Path('config/scoring_overrides.yaml')
if override_path.exists():
    with open(override_path) as f:
        result['overrides'] = yaml.safe_load(f)
else:
    result['overrides'] = 'NOT FOUND (no overrides)'

# 5. Runtime resolved values
from backend.scoring.config_loader import ScoringConfigLoader
loader = ScoringConfigLoader()
config = loader.load()
result['runtime_resolved'] = {
    'version': config.version,
    'simgr_weights': asdict(config.simgr_weights),
    'study_factors': asdict(config.study_factors),
    'interest_factors': asdict(config.interest_factors),
    'market_factors': asdict(config.market_factors),
    'growth_factors': asdict(config.growth_factors),
    'risk_factors': asdict(config.risk_factors),
    'thresholds': asdict(config.thresholds),
    'data_freshness': asdict(config.data_freshness),
    'features': asdict(config.features),
    'source': config._source
}

# Write output
with open('baseline/baseline_config_snapshot.json', 'w') as f:
    json.dump(result, f, indent=2)

print('Config snapshot saved.')
print('SIMGR Weights:', result['runtime_resolved']['simgr_weights'])
