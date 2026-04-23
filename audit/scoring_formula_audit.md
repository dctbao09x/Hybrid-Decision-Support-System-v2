# Scoring Formula Audit Report
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** Code-only analysis (no documentation, no comments, no assumptions)

---

## 1. Runtime Formula Verification

### Source Location
- **File:** [backend/scoring/calculator.py](../backend/scoring/calculator.py#L102-L110)
- **Lines:** 102-110

### Extracted Runtime Formula
```python
total_score = (
    simgr_scores.get("study", 0.5) * weights.study_score +
    simgr_scores.get("interest", 0.5) * weights.interest_score +
    simgr_scores.get("market", 0.5) * weights.market_score +
    simgr_scores.get("growth", 0.5) * weights.growth_score -
    simgr_scores.get("risk", 0.0) * weights.risk_score  # SUBTRACT risk
)
```

### Canonical Form
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
```

### Risk Subtraction: **VERIFIED**
- Risk coefficient is **SUBTRACTED** (minus sign at line 108)
- Risk fallback is 0.0 (not 0.5) - **INTENTIONAL** to avoid penalizing when risk unknown

---

## 2. Coefficients Identified

| Component | Weight Key | Default Value | Source |
|-----------|------------|---------------|--------|
| Study (S) | `study_score` | 0.25 | config.py:30 |
| Interest (I) | `interest_score` | 0.25 | config.py:31 |
| Market (M) | `market_score` | 0.25 | config.py:32 |
| Growth (G) | `growth_score` | 0.15 | config.py:33 |
| Risk (R) | `risk_score` | 0.10 | config.py:34 |

**Sum Validation:** 0.25 + 0.25 + 0.25 + 0.15 + 0.10 = **1.00** ✓

---

## 3. Clamp/Normalize Logic

### Source: [normalizer.py](../backend/scoring/normalizer.py#L58-L94)

```python
@staticmethod
def clamp(
    value: Number,
    min_val: Number = 0.0,
    max_val: Number = 1.0,
) -> float:
```

### Boundary Handling
| Input | Output | Evidence |
|-------|--------|----------|
| `None` | 0.0 | Runtime test confirmed |
| `NaN` | 0.0 | Runtime test confirmed |
| `+Inf` | 1.0 | Runtime test confirmed |
| `-Inf` | 0.0 | Runtime test confirmed |
| `< 0` | 0.0 | Code: `max(min_val, ...)` |
| `> 1` | 1.0 | Code: `min(..., max_val)` |

---

## 4. Numeric Validation (Runtime Test)

### Test Input
```python
weights = SIMGRWeights(
    study_score=0.25,
    interest_score=0.20,
    market_score=0.20,
    growth_score=0.20,
    risk_score=0.15
)
```

### Test Output
```
Total Score: 0.38091875
Breakdown: {
    'study_score': 0.65,
    'interest_score': 0.21,
    'market_score': 0.58,
    'growth_score': 0.7722,
    'risk_score': 0.6269
}
```

### Manual Calculation
```
= 0.25*0.65 + 0.20*0.21 + 0.20*0.58 + 0.20*0.7722 - 0.15*0.6269
= 0.1625 + 0.042 + 0.116 + 0.15444 - 0.094035
= 0.380905
```

### Verification: **MATCH** (difference < 0.0001)

---

## 5. Fallback Values

| Component | Fallback | Location | Risk Level |
|-----------|----------|----------|------------|
| study | 0.5 | calculator.py:96 | MEDIUM |
| interest | 0.5 | calculator.py:96 | MEDIUM |
| market | 0.5 | calculator.py:96 | MEDIUM |
| growth | 0.5 | calculator.py:96 | MEDIUM |
| risk | 0.0 | calculator.py:108 | **LOW** (intentional) |

### Finding: **SILENT FALLBACK EXISTS**
When a component fails, it silently returns 0.5 with `fallback: true` in meta.
This is logged but **NOT propagated to caller**.

---

## 6. Formula Audit Status

| Check | Status | Evidence |
|-------|--------|----------|
| Formula documented in code | ✓ | calculator.py:102 comment |
| Risk SUBTRACTED | ✓ | Minus sign at line 108 |
| Weights sum to 1.0 | ✓ | Validated in SIMGRWeights.__post_init__ |
| Scores clamped [0,1] | ✓ | normalizer.clamp() call at line 112 |
| Handles edge cases | ✓ | None/NaN/Inf all handled |
| Fallback documented | **PARTIAL** | Logged but not in API response |

---

## 7. Verdict

**FORMULA: PASS**

The runtime formula correctly implements `Score = wS*S + wI*I + wM*M + wG*G - wR*R` with proper risk subtraction and boundary handling.

**CONCERNS:**
1. Component fallback to 0.5 is silent (logged only)
2. Risk fallback of 0.0 differs from other components (by design)
