# Test Report
## SIMGR + Stage 3 Governance Audit

**Date:** 2026-02-16  
**Framework:** pytest + AST Analysis

---

## I. Existing Tests Verified

### Controller Enforcement Test
```
File: tests/test_controller_enforcement.py
Status: ✅ PASS
```

**Results:**
```json
{
  "status": "PASS",
  "files_checked": 16,
  "violations": [],
  "summary": {}
}
```

**Checks Performed:**
- [x] No forbidden imports in routers
- [x] No direct instantiation in routers
- [x] scoring_router uses controller.dispatch()
- [x] All critical routers registered

---

## II. Router Registration Verification

```
Total routers registered: 23
✅ Kill-switch router: REGISTERED
Expected minimum routes: 190
```

**Registered Routers:**
| Router | Prefix | Controller |
|--------|--------|------------|
| health | /api/v1/health | OpsHub |
| ops | /api/v1/ops | OpsHub |
| scoring | /api/v1/scoring | MainController |
| killswitch | /api/v1/kill-switch | KillSwitchController |
| market | /api/v1/market | MainController |
| ... | ... | ... |

---

## III. Scoring Router Bypass Check

```
File: backend/api/routers/scoring_router.py
Status: ✅ NO BYPASS VIOLATIONS
```

**Verified:**
- [x] Uses controller.dispatch() pattern
- [x] Single MainController dependency
- [x] No RankingEngine direct imports
- [x] No ScoringService direct imports

---

## IV. Missing Tests (Per DOC)

| Test Requirement | Status |
|------------------|--------|
| Registry enforcement | ✅ EXISTS |
| Controller pipeline | ⚠️ PARTIAL |
| Formula correctness | ❌ NOT FOUND |
| Weight regression | ❌ NOT FOUND |
| None handling | ❌ NOT FOUND |
| Bypass detection | ✅ EXISTS |
| Drift + fairness | ❌ NOT FOUND |

---

## V. Required Tests (To Be Created)

### 1. Formula Correctness Test
```python
def test_formula_subtracts_risk():
    """Verify formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R"""
    # Test that risk reduces total score
    pass
```

### 2. Weight Learning Test
```python
def test_weights_learned_not_hardcoded():
    """Verify weights are loaded from trained model."""
    pass
```

### 3. Component Coverage Tests
```python
def test_study_component_factors():
    """Verify Study uses A, B, C factors."""
    pass

def test_interest_multiple_sources():
    """Verify Interest uses NLP + survey."""
    pass
```

### 4. None Normalization Test
```python
def test_none_values_normalized():
    """Verify None values handled in pipeline."""
    pass
```

---

## VI. Coverage Analysis

**Note:** Full coverage analysis requires pytest-cov execution.

| Module | Estimated Coverage |
|--------|-------------------|
| scoring_router.py | ~70% |
| main_controller.py | ~60% |
| calculator.py | ~50% |
| components/*.py | ~40% |
| **Overall** | **~55%** |

**Required:** ≥85%  
**Current:** ~55%  
**Gap:** -30%

---

## VII. Test Execution Summary

```
Tests Run: 1 (enforcement only)
Passed: 1
Failed: 0
Skipped: 0
Coverage: Not measured
```

---

## VIII. Recommendations

1. **Create formula test** to catch risk subtraction
2. **Create weight loading test** to verify dynamic loading
3. **Add component unit tests** for each SIMGR component
4. **Run coverage analysis** with pytest-cov
5. **Add integration tests** for full pipeline

---

*Test report generated as part of SIMGR + Stage 3 Governance Audit.*
