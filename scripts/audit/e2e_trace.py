# Scoring Integrity Test - End-to-End Trace
"""
Verify all SIMGR components are connected and compute real values.
"""

import json
from pathlib import Path

def run_e2e_test():
    # Load weights directly
    weights_path = Path("models/weights/active/weights.json")
    with open(weights_path) as f:
        weights_data = json.load(f)
    
    print("=== WEIGHTS FROM FILE ===")
    print(f"Path: {weights_path}")
    print(f"Version: {weights_data.get('version')}")
    print(f"Trained At: {weights_data.get('trained_at')}")
    print(f"Method: {weights_data.get('metrics', {}).get('method', 'unknown')}")
    print()
    
    weights = weights_data.get('weights', {})
    print("Weight Values:")
    print(f"  wS (study): {weights.get('study_score')}")
    print(f"  wI (interest): {weights.get('interest_score')}")
    print(f"  wM (market): {weights.get('market_score')}")
    print(f"  wG (growth): {weights.get('growth_score')}")
    print(f"  wR (risk): {weights.get('risk_score')}")
    
    total = sum(weights.values())
    print(f"\nWeights Sum: {total}")
    
    # Import components directly
    print("\n=== COMPONENT IMPORTS ===")
    
    try:
        from backend.scoring.components import study
        print(f"study.score: {study.score}")
    except Exception as e:
        print(f"study: FAILED - {e}")
    
    try:
        from backend.scoring.components import interest
        print(f"interest.score: {interest.score}")
    except Exception as e:
        print(f"interest: FAILED - {e}")
    
    try:
        from backend.scoring.components import market
        print(f"market.score: {market.score}")
    except Exception as e:
        print(f"market: FAILED - {e}")
    
    try:
        from backend.scoring.components import growth
        print(f"growth.score: {growth.score}")
    except Exception as e:
        print(f"growth: FAILED - {e}")
    
    try:
        from backend.scoring.components import risk
        print(f"risk.score: {risk.score}")
    except Exception as e:
        print(f"risk: FAILED - {e}")
    
    # Test formula
    print("\n=== FORMULA TEST ===")
    from backend.scoring.scoring_formula import ScoringFormula
    
    test_scores = {
        "study": 0.8,
        "interest": 0.7,
        "market": 0.85,
        "growth": 0.9,
        "risk": 0.3,
    }
    
    test_weights = {
        "study": weights.get('study_score', 0.25),
        "interest": weights.get('interest_score', 0.25),
        "market": weights.get('market_score', 0.25),
        "growth": weights.get('growth_score', 0.15),
        "risk": weights.get('risk_score', 0.10),
    }
    
    result = ScoringFormula.compute(test_scores, test_weights)
    
    # Manual verification
    manual = (
        test_weights["study"] * test_scores["study"] +
        test_weights["interest"] * test_scores["interest"] +
        test_weights["market"] * test_scores["market"] +
        test_weights["growth"] * test_scores["growth"] -
        test_weights["risk"] * test_scores["risk"]
    )
    
    print(f"Input Scores: {test_scores}")
    print(f"Input Weights: {test_weights}")
    print(f"Formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R")
    print(f"ScoringFormula.compute(): {result:.4f}")
    print(f"Manual Calculation: {manual:.4f}")
    print(f"Match: {abs(result - manual) < 0.0001}")


if __name__ == '__main__':
    run_e2e_test()
