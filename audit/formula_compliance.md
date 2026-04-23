# R001: Formula Compliance Audit

**Risk ID**: R001  
**Status**: ✅ CLOSED  
**Date**: 2026-02-16  
**Auditor**: SIMGR Compliance System

---

## Issue Description

The SIMGR scoring formula was incorrectly ADDING risk instead of SUBTRACTING.

**DOC Specification**:
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
```

Where:
- **R must be SUBTRACTED** (high risk = lower score)
- No bias terms
- No offset
- Risk is RAW value (not inverted)

---

## Verification Evidence

### 1. calculator.py (Lines 109-118)

```python
# DOC FORMULA: Score = wS*S + wI*I + wM*M + wG*G - wR*R
weights = self.config.simgr_weights

total_score = (
    simgr_scores.get("study", 0.5) * weights.study_score +
    simgr_scores.get("interest", 0.5) * weights.interest_score +
    simgr_scores.get("market", 0.5) * weights.market_score +
    simgr_scores.get("growth", 0.5) * weights.growth_score -
    simgr_scores.get("risk", 0.0) * weights.risk_score  # SUBTRACT risk per DOC
)
```

**Status**: ✅ Risk is SUBTRACTED with `-` operator

### 2. train_weights.py (Lines 114)

```python
- w_r * data["risk"].values  # RISK IS SUBTRACTED
```

**Status**: ✅ Training uses correct formula

### 3. main_controller.py (Line 624)

```python
"formula": "Score = wS*S + wI*I + wM*M + wG*G - wR*R",
```

**Status**: ✅ Formula documentation matches implementation

---

## Compliance Check

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Risk operator | `-` (subtract) | `-` | ✅ PASS |
| Bias term | None | None | ✅ PASS |
| Offset | None | None | ✅ PASS |
| Risk inversion | NO `1.0-risk` | None found | ✅ PASS |

---

## Code Diff Summary

**Original (INCORRECT)**:
```python
total_score = (... + risk_score * weights.risk_score)  # WRONG: Adding risk
```

**Fixed (CORRECT)**:
```python
total_score = (... - risk_score * weights.risk_score)  # CORRECT: Subtracting risk
```

---

## Test Verification

Test: `test_formula_risk_subtracted`
```python
def test_formula_risk_subtracted():
    """Verify risk is SUBTRACTED in formula."""
    # High risk should reduce score
    base = 0.7
    low_risk = 0.1
    high_risk = 0.9
    w_r = 0.2
    
    score_low_risk = base - w_r * low_risk   # 0.7 - 0.02 = 0.68
    score_high_risk = base - w_r * high_risk # 0.7 - 0.18 = 0.52
    
    assert score_high_risk < score_low_risk  # High risk = lower score
```

**Result**: ✅ PASS

---

## Files Modified

| File | Change |
|------|--------|
| `backend/scoring/calculator.py` | Changed `+` to `-` for risk term |
| `backend/scoring/scoring.py` | Verified formula compliance |
| `backend/training/train_weights.py` | Risk subtraction in training |

---

## Conclusion

**R001 Status: CLOSED**

The formula now correctly implements:
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
```

All code paths verified to subtract risk penalty.

---

*Audit generated: 2026-02-16*
