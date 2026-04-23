#!/usr/bin/env python
"""
Baseline Snapshot Builder
Combines all baseline data into single JSON.
"""
import sys
sys.path.insert(0, '.')

import json
import os
import hashlib
from datetime import datetime
from pathlib import Path

def file_hash(path):
    """Get SHA256 hash of file."""
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

def read_json(path):
    """Read JSON file."""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def read_text(path):
    """Read text file."""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()

# Build snapshot
snapshot = {
    "timestamp": datetime.now().isoformat(),
    "git": {},
    "weights": {},
    "config": {},
    "runtime": {},
    "coverage": {},
    "environment": {},
    "hashes": {}
}

# Git state
git_state_path = "baseline/baseline_git_state.txt"
git_content = read_text(git_state_path)
if git_content:
    snapshot["git"] = {
        "commit": "156b70eeb9a116a1d7efe7edb23cecf31abf4bcd",
        "branch": "master",
        "tag": "scoring_baseline_fail",
        "dirty_count": 325,
        "raw": git_content[:500]
    }
    snapshot["hashes"]["git_state"] = file_hash(git_state_path)

# Weights
weights_path = "baseline/baseline_weights.json"
snapshot["weights"] = read_json(weights_path) or "NOT FOUND"
snapshot["hashes"]["weights"] = file_hash(weights_path)

# Config
config_path = "baseline/baseline_config_snapshot.json"
snapshot["config"] = read_json(config_path) or "NOT FOUND"
snapshot["hashes"]["config"] = file_hash(config_path)

# Runtime log summary
runtime_path = "baseline/baseline_runtime.log"
runtime_content = read_text(runtime_path)
if runtime_content:
    # Extract key info
    lines = runtime_content.split('\n')
    snapshot["runtime"] = {
        "total_lines": len(lines),
        "scoring_results": [],
        "errors": [],
        "summary": runtime_content[:2000]
    }
    for line in lines:
        if "Ranking complete" in line:
            snapshot["runtime"]["scoring_results"].append(line.strip())
        if "ERROR" in line:
            snapshot["runtime"]["errors"].append(line.strip()[:200])
    snapshot["hashes"]["runtime"] = file_hash(runtime_path)

# Coverage summary
coverage_path = "baseline/baseline_coverage.txt"
coverage_content = read_text(coverage_path)
if coverage_content:
    snapshot["coverage"] = {
        "total_percent": 40.31,
        "passed": 99,
        "failed": 3,
        "failed_tests": [
            "test_rank_careers_baseline_compatibility",
            "test_score_direct_components_valid",
            "test_score_direct_components_custom_config"
        ],
        "raw_summary": coverage_content[-2000:]
    }
    snapshot["hashes"]["coverage"] = file_hash(coverage_path)

# Environment
snapshot["environment"] = {
    "python_version": sys.version,
    "platform": sys.platform,
    "cwd": os.getcwd()
}

# Write snapshot
output_path = "baseline/baseline_snapshot.json"
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(snapshot, f, indent=2, default=str)

print(f"Baseline snapshot saved to: {output_path}")
print(f"Timestamp: {snapshot['timestamp']}")
print(f"Git commit: {snapshot['git'].get('commit', 'N/A')}")
print(f"Coverage: {snapshot['coverage'].get('total_percent', 'N/A')}%")
print(f"Failed tests: {snapshot['coverage'].get('failed', 'N/A')}")
