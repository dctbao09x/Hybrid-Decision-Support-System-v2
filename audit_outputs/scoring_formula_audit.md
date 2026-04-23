# Scoring Formula Audit Report
## SIMGR + Stage 3 Full Governance Audit

**Date:** 2026-02-16  
**Auditor:** Principal System Architect  
**Status:** ❌ FAIL

---

## I. MANDATORY FORMULA VERIFICATION

### DOC Requirement:
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
```

### Actual Implementation:

#### File: `backend/scoring/calculator.py` (Lines 101-107)
```python
total_score = (
    simgr_scores.get("study", 0.5) * weights.study_score +
    simgr_scores.get("interest", 0.5) * weights.interest_score +
    simgr_scores.get("market", 0.5) * weights.market_score +
    simgr_scores.get("growth", 0.5) * weights.growth_score +
    simgr_scores.get("risk", 0.5) * weights.risk_score  # ❌ ADDS risk
)
```

#### File: `backend/scoring/scoring.py` (Lines 227-233)
```python
total_score = (
    study * config.simgr_weights.study_score +
    interest * config.simgr_weights.interest_score +
    market * config.simgr_weights.market_score +
    growth * config.simgr_weights.growth_score +
    risk * config.simgr_weights.risk_score  # ❌ ADDS risk
)
```

### Verdict: ❌ FORMULA VIOLATION

| Component | DOC Operator | Actual Operator | Status |
|-----------|--------------|-----------------|--------|
| S (Study) | + | + | ✅ PASS |
| I (Interest) | + | + | ✅ PASS |
| M (Market) | + | + | ✅ PASS |
| G (Growth) | + | + | ✅ PASS |
| R (Risk) | **-** | **+** | ❌ **FAIL** |

---

## II. RISK COMPONENT ANALYSIS

### File: `backend/scoring/components/risk.py`

The risk component inverts the score:
```python
# Line 51
risk_score = normalizer.clamp(1.0 - total_risk)
```

**Issue:** The component outputs `1.0 - total_risk` (inverted), then the calculator **ADDS** this value.

**DOC Requirement:** Formula should **SUBTRACT** risk: `- wR*R`

**Mathematical Equivalence Check:**
- Current: `Score = ... + wR * (1 - raw_risk)`
- Expanded: `Score = ... + wR - wR*raw_risk`
- DOC: `Score = ... - wR*R`

These are **NOT** equivalent unless wR is subtracted separately, which it isn't.

---

## III. FIX REQUIRED

### Option A: Change Calculator Formula (Recommended)
```python
# calculator.py line 101-107
total_score = (
    simgr_scores.get("study", 0.5) * weights.study_score +
    simgr_scores.get("interest", 0.5) * weights.interest_score +
    simgr_scores.get("market", 0.5) * weights.market_score +
    simgr_scores.get("growth", 0.5) * weights.growth_score -
    simgr_scores.get("risk", 0.5) * weights.risk_score  # ✅ SUBTRACT
)
```

### Option B: Change Risk Component Output
Keep risk as raw (0.0 = low risk, 1.0 = high risk) instead of inverting.

---

## IV. WEIGHT VALIDATION

### File: `backend/scoring/config.py` (Lines 22-27)

```python
@dataclass
class SIMGRWeights:
    study_score: float = 0.25
    interest_score: float = 0.25
    market_score: float = 0.25
    growth_score: float = 0.15
    risk_score: float = 0.10
```

**Sum Validation:**
```
0.25 + 0.25 + 0.25 + 0.15 + 0.10 = 1.00 ✅
```

**Status:** ✅ Weights sum to 1.0

---

## V. SUMMARY

| Check | Status |
|-------|--------|
| Formula structure exists | ✅ PASS |
| 5 components present | ✅ PASS |
| Weights sum to 1.0 | ✅ PASS |
| Risk subtraction | ❌ FAIL |
| Formula matches DOC | ❌ FAIL |

---

## VI. FINAL VERDICT

### **❌ FAIL** - Formula does not match DOC specification.

**Critical Issue:** Risk score is ADDED instead of SUBTRACTED.

**Required Action:** Fix formula in `calculator.py` and `scoring.py` to subtract risk.

---

*Audit conducted with code-backed evidence only. No assumptions made.*
