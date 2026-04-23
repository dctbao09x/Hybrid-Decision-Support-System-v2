#!/usr/bin/env python
"""
Weight Source Audit Script - GĐ1 PHẦN A
Scan toàn bộ repo tìm hardcoded weights, fallbacks, magic numbers.
"""
import sys
sys.path.insert(0, '.')

import json
import re
import os
from pathlib import Path
from typing import List, Dict, Any

SCORING_DIR = Path("backend/scoring")

# Patterns to detect
WEIGHT_PATTERNS = [
    # Direct SIMGR weight assignments
    (r'study_score\s*[:=]\s*0\.', 'study_score default'),
    (r'interest_score\s*[:=]\s*0\.', 'interest_score default'),
    (r'market_score\s*[:=]\s*0\.', 'market_score default'),
    (r'growth_score\s*[:=]\s*0\.', 'growth_score default'),
    (r'risk_score\s*[:=]\s*0\.', 'risk_score default'),
    # Short names
    (r'\bws\s*[:=]\s*0\.\d', 'ws magic number'),
    (r'\bwi\s*[:=]\s*0\.\d', 'wi magic number'),
    (r'\bwm\s*[:=]\s*0\.\d', 'wm magic number'),
    (r'\bwg\s*[:=]\s*0\.\d', 'wg magic number'),
    (r'\bwr\s*[:=]\s*0\.\d', 'wr magic number'),
    # Fallback patterns
    (r'\.get\(["\']study_score["\'],\s*0\.', 'study_score fallback'),
    (r'\.get\(["\']interest_score["\'],\s*0\.', 'interest_score fallback'),
    (r'\.get\(["\']market_score["\'],\s*0\.', 'market_score fallback'),
    (r'\.get\(["\']growth_score["\'],\s*0\.', 'growth_score fallback'),
    (r'\.get\(["\']risk_score["\'],\s*0\.', 'risk_score fallback'),
    # Default class instances
    (r'return\s+cls\(\)', 'default instance return'),
    (r'Using default weights', 'fallback warning'),
]

def scan_file(file_path: Path) -> List[Dict[str, Any]]:
    """Scan a single file for weight patterns."""
    results = []
    
    try:
        content = file_path.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            for pattern, type_name in WEIGHT_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    # Determine component from pattern
                    component = "SIMGR"
                    if 'study' in pattern.lower() or pattern.startswith(r'\bws'):
                        component = "S"
                    elif 'interest' in pattern.lower() or pattern.startswith(r'\bwi'):
                        component = "I"
                    elif 'market' in pattern.lower() or pattern.startswith(r'\bwm'):
                        component = "M"
                    elif 'growth' in pattern.lower() or pattern.startswith(r'\bwg'):
                        component = "G"
                    elif 'risk' in pattern.lower() or pattern.startswith(r'\bwr'):
                        component = "R"
                    
                    # Determine type
                    weight_type = "default"
                    if "fallback" in type_name:
                        weight_type = "fallback"
                    elif "magic" in type_name:
                        weight_type = "magic_number"
                    
                    results.append({
                        "component": component,
                        "file": str(file_path),
                        "line": line_num,
                        "type": weight_type,
                        "pattern": type_name,
                        "code": line.strip()[:100],
                        "active": True  # Will determine later
                    })
    except Exception as e:
        print(f"Error scanning {file_path}: {e}")
    
    return results

def audit_weights() -> Dict[str, Any]:
    """Full weight source audit."""
    all_results = []
    
    # Scan scoring directory
    for py_file in SCORING_DIR.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        results = scan_file(py_file)
        all_results.extend(results)
    
    # Group by file
    by_file = {}
    for r in all_results:
        file = r["file"]
        if file not in by_file:
            by_file[file] = []
        by_file[file].append(r)
    
    # Runtime path trace
    runtime_path = [
        {"step": 1, "file": "backend/scoring/config.py", "function": "SIMGRWeights.from_file()", "note": "Primary weight loading"},
        {"step": 2, "file": "backend/scoring/config.py", "function": "_load_default_config()", "note": "DEFAULT_CONFIG initialization"},
        {"step": 3, "file": "backend/scoring/engine.py", "function": "RankingEngine.__init__()", "note": "Uses DEFAULT_CONFIG"},
        {"step": 4, "file": "backend/scoring/strategies.py", "function": "WeightedScoringStrategy", "note": "Applies weights to scores"},
    ]
    
    # Critical files
    critical_files = [
        "backend/scoring/config.py",
        "backend/scoring/config_loader.py",
        "backend/scoring/engine.py",
        "backend/scoring/strategies.py",
    ]
    
    # Summary
    summary = {
        "total_hardcoded": len(all_results),
        "by_type": {},
        "by_component": {},
        "critical_files": []
    }
    
    for r in all_results:
        t = r["type"]
        c = r["component"]
        summary["by_type"][t] = summary["by_type"].get(t, 0) + 1
        summary["by_component"][c] = summary["by_component"].get(c, 0) + 1
        
        if any(cf in r["file"] for cf in critical_files):
            if r["file"] not in summary["critical_files"]:
                summary["critical_files"].append(r["file"])
    
    return {
        "audit_timestamp": "2026-02-16",
        "summary": summary,
        "runtime_path": runtime_path,
        "sources": all_results,
        "by_file": by_file
    }

if __name__ == "__main__":
    print("=" * 80)
    print("WEIGHT SOURCE AUDIT - GĐ1 PHẦN A")
    print("=" * 80)
    
    result = audit_weights()
    
    # Save to file
    with open("weight_governance/weight_source_map.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nTotal hardcoded weights found: {result['summary']['total_hardcoded']}")
    print(f"\nBy type:")
    for t, count in result['summary']['by_type'].items():
        print(f"  {t}: {count}")
    
    print(f"\nBy component:")
    for c, count in result['summary']['by_component'].items():
        print(f"  {c}: {count}")
    
    print(f"\nCritical files:")
    for f in result['summary']['critical_files']:
        print(f"  {f}")
    
    print(f"\nRuntime path:")
    for step in result['runtime_path']:
        print(f"  {step['step']}. {step['file']} -> {step['function']}")
    
    print(f"\nOutput: weight_governance/weight_source_map.json")