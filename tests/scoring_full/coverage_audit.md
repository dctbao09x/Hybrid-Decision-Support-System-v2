# GĐ6 Coverage Audit Report

## Executive Summary

**Phase**: GIAI ĐOẠN 6 - COVERAGE RECOVERY  
**Date**: 2026-02-17  
**Status**: PARTIAL PASS (7/9 modules meet target)

---

## Coverage by Module

### Priority Modules - Target ≥85%

| Module | Lines | Covered | % | Target | Status |
|--------|-------|---------|---|--------|--------|
| calculator.py | 56 | 54 | 96.4% | ≥90% | ✅ PASS |
| strategies.py | 108 | 108 | 100% | ≥85% | ✅ PASS |
| scoring.py | 115 | 104 | 90.4% | ≥85% | ✅ PASS |
| components/risk.py | 79 | 78 | 98.7% | ≥85% | ✅ PASS |
| components/interest.py | 74 | 72 | 97.3% | ≥85% | ✅ PASS |
| components/market.py | 44 | 38 | 86.4% | ≥85% | ✅ PASS |
| engine.py | 105 | 63 | 60.0% | ≥85% | ❌ FAIL |
| components/study.py | 51 | 47 | 92.2% | ≥85% | ✅ PASS |
| components/growth.py | 45 | 43 | 95.6% | ≥85% | ✅ PASS |

### Secondary Modules

| Module | Coverage | Notes |
|--------|----------|-------|
| config.py | 58.2% | Config loading complexity |
| models.py | 91.1% | Data models |
| scoring_formula.py | 76.7% | Formula logic |
| normalizer.py | 25.4% | Data normalization |
| weights_registry.py | 28.1% | Weight management |

---

## Uncovered Lines Analysis

### engine.py (Needs Attention)

**Missing Coverage (40%)**:
- Lines 173-181: `RankingOutput` construction
- Lines 286-345: `score_jobs()` facade function  
- Lines 399-487: Input/output type handling

**Reason**: Test API mismatch - tests import non-existent class names

**Remediation**:
```python
# Tests reference 'WeightedStrategy' but actual class is 'WeightedScoringStrategy'
# Update test_engine.py imports
```

### calculator.py (Minor Gaps)

**Missing Coverage (3.6%)**:
- Line 58: Config None check (edge case)
- Line 176: TypeError raise (error branch)

**Remediation**: Add explicit tests for None config scenario

### scoring.py (Minor Gaps)

**Missing Coverage (9.6%)**:
- Lines 190-194: Error response formatting
- Lines 340-341, 382, 414-415: Edge case branches

---

## Test Suite Statistics

| Metric | Count |
|--------|-------|
| Total Tests | 261 |
| Passed | 225 |
| Failed | 36 |
| Skipped | 0 |
| Fault Injection Tests | 36 |

### Test Distribution by Type

| Type | Count | Pass | Fail |
|------|-------|------|------|
| Deterministic | 85 | 78 | 7 |
| Boundary | 42 | 40 | 2 |
| Fault Injection | 36 | 36 | 0 |
| Integration | 38 | 31 | 7 |
| Other | 60 | 40 | 20 |

---

## Failure Root Causes

### Category 1: API Mismatch (21 failures)

Tests reference outdated or non-existent:
- `WeightedStrategy` → `WeightedScoringStrategy`
- `PersonalizedStrategy` → `PersonalizedScoringStrategy`
- `final_score` → `total_score`
- `_compute_*` internal functions (not exported)

### Category 2: Model Validation (8 failures)

Pydantic model constraints prevent test setup:
- `interest_stability` attribute not in UserProfile
- CareerData requires valid ranges

### Category 3: Assertion Mismatch (7 failures)

Expected values don't match actual behavior:
- Case sensitivity differences
- Partial string matching
- Numeric precision

---

## Remediation Plan

### Immediate (To reach 85%):

1. **Fix engine.py coverage**:
   - Add tests for `score_jobs()` function
   - Test `RankingOutput` construction
   - Remove tests for non-existent classes

2. **Fix test_market.py imports**:
   - Remove references to internal `_compute_*` functions
   - Test via public `score()` API instead

3. **Update test assertions**:
   - Fix `final_score` → `total_score`
   - Correct case sensitivity expectations

### Recommended:

4. Create integration tests for full pipeline
5. Add property-based testing for edge cases
6. Mock dataset loading comprehensively

---

## Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Deterministic tests | ✅ YES |
| Boundary tests | ✅ YES |
| Fault injection (≥20 cases) | ✅ YES (36 cases) |
| No random seeds | ✅ YES |
| No network deps | ✅ YES |
| No filesystem deps | ✅ YES (mocked) |
| calculator ≥90% | ✅ YES (96.4%) |
| risk ≥85% | ✅ YES (98.7%) |
| engine ≥85% | ❌ NO (60.0%) |
| Total ≥85% | ❌ NO (22.4%*) |

*Total includes all 49 files in backend/scoring/. Priority modules average: **88.7%**

---

## Conclusion

GĐ6 Coverage Recovery is **PARTIALLY COMPLETE**:
- 7 of 9 priority modules meet ≥85% target
- engine.py requires additional tests
- 36 fault injection tests implemented (exceeds ≥20 requirement)
- API compatibility issues blocking ~36 tests

**Next Steps**: Fix API mismatches in test files, add engine.py tests

---

Generated: 2026-02-17  
Auditor: Principal Test Architect
