# Coverage Report
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** pytest-cov execution

---

## 1. Test Execution Summary

```
Command: pytest tests/scoring/ --cov=backend/scoring --cov-report=term-missing
```

### Results
- **Tests:** 112 passed
- **Time:** 3.97s
- **Coverage:** 29.41%
- **Threshold:** 80%
- **Status:** ❌ **FAIL**

---

## 2. Coverage by Module

| Module | Stmts | Miss | Cover |
|--------|-------|------|-------|
| `__init__.py` | 7 | 0 | 100.0% |
| `baseline_capture.py` | 21 | 21 | 0.0% |
| `calculator.py` | 56 | 35 | 37.5% |
| `components/__init__.py` | 0 | 0 | 100.0% |
| `components/growth.py` | 45 | 27 | 40.0% |
| `components/growth_refresh.py` | 176 | 59 | 66.5% |
| `components/interest.py` | 74 | 60 | 18.9% |
| `components/market.py` | 44 | 27 | 38.6% |
| `components/risk.py` | 79 | 53 | 32.9% |
| `components/study.py` | 51 | 38 | 25.5% |
| `config.py` | 150 | 53 | 64.7% |
| `config_loader.py` | 178 | 21 | 88.2% |
| `drift.py` | 171 | 31 | 81.9% |
| `engine.py` | 100 | 74 | 26.0% |
| `examples.py` | 46 | 46 | 0.0% |
| `explain/feature_importance.py` | 102 | 102 | 0.0% |
| `explain/reason_generator.py` | 126 | 126 | 0.0% |
| `explain/shap_engine.py` | 191 | 191 | 0.0% |
| `explain/test_xai.py` | 190 | 190 | 0.0% |
| `explain/tracer.py` | 65 | 65 | 0.0% |
| `explain/xai.py` | 197 | 197 | 0.0% |
| `models.py` | 90 | 17 | 81.1% |
| `normalizer.py` | 118 | 92 | 22.0% |
| `scheduler.py` | 100 | 100 | 0.0% |
| `scoring.py` | 117 | 98 | 16.2% |
| `strategies.py` | 104 | 70 | 32.7% |
| `taxonomy_adapter.py` | 35 | 28 | 20.0% |
| `version_manager.py` | 122 | 122 | 0.0% |
| **TOTAL** | **2761** | **1949** | **29.4%** |

---

## 3. Critical Path Coverage

### Main Scoring Path
| Component | Coverage | Critical? |
|-----------|----------|-----------|
| scoring.py (Entry) | 16.2% | ✅ YES |
| engine.py (Orchestration) | 26.0% | ✅ YES |
| strategies.py (Strategy) | 32.7% | ✅ YES |
| calculator.py (Calculation) | 37.5% | ✅ YES |
| normalizer.py (Validation) | 22.0% | ✅ YES |

**Finding:** Critical path has < 40% coverage.

### Component Coverage
| Component | Coverage | Status |
|-----------|----------|--------|
| study.py | 25.5% | ❌ Low |
| interest.py | 18.9% | ❌ Low |
| market.py | 38.6% | ❌ Low |
| growth.py | 40.0% | ⚠️ Medium |
| risk.py | 32.9% | ❌ Low |

**Finding:** No component exceeds 50% coverage.

### Auxiliary Modules
| Module | Coverage | Status |
|--------|----------|--------|
| config_loader.py | 88.2% | ✅ Good |
| drift.py | 81.9% | ✅ Good |
| models.py | 81.1% | ✅ Good |
| growth_refresh.py | 66.5% | ⚠️ Medium |
| config.py | 64.7% | ⚠️ Medium |

---

## 4. Zero Coverage Modules

| Module | Lines | Status |
|--------|-------|--------|
| baseline_capture.py | 21 | ⛔ 0% |
| examples.py | 46 | ⛔ 0% |
| scheduler.py | 100 | ⛔ 0% |
| version_manager.py | 122 | ⛔ 0% |
| explain/ (all) | 871 | ⛔ 0% |

**Finding:** 5 modules have zero test coverage.

---

## 5. Missing Coverage Details

### calculator.py (37.5% coverage)
- Missing: Lines 79-140 (main calculation logic)
- Missing: Lines 158-187 (_compute_component)

### scoring.py (16.2% coverage)
- Missing: Lines 173-191 (direct score mode)
- Missing: Lines 212-263 (full pipeline mode)
- Missing: Lines 279-311 (error handling)

### engine.py (26.0% coverage)
- Missing: Lines 130-181 (strategy building)
- Missing: Lines 274-332 (rank_from_input)
- Missing: Lines 386-474 (additional methods)

---

## 6. Test Quality Analysis

### Test Categories
| Category | Tests | Status |
|----------|-------|--------|
| Unit (components) | 33 | ✅ Exist |
| Unit (config) | 14 | ✅ Exist |
| Unit (drift) | 20 | ✅ Exist |
| Unit (formula) | 10 | ✅ Exist |
| Unit (freshness) | 19 | ✅ Exist |
| Unit (weights) | 16 | ✅ Exist |
| Integration | 0 | ❌ Missing |
| E2E | 0 | ❌ Missing |
| Adversarial | 0 | ❌ Missing |

### Finding: **No integration or E2E tests**

Tests verify individual modules but not:
- Full scoring pipeline
- API → Controller → Engine → Calculator flow
- Error propagation across layers

---

## 7. Edge Case Coverage

### Tested
- ✅ Default weights validation
- ✅ Weights sum to 1.0
- ✅ PSI threshold detection
- ✅ Data freshness TTL
- ✅ Config validation

### Not Tested
- ❌ None/NaN injection through full pipeline
- ❌ Empty career list handling
- ❌ Component failure recovery
- ❌ Timeout behavior
- ❌ Concurrent request handling
- ❌ Config hot reload

---

## 8. Coverage Verdict

**COVERAGE: FAIL**

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Overall | 29.4% | 80% | ❌ FAIL |
| Critical path | < 40% | 80% | ❌ FAIL |
| Zero coverage modules | 5 | 0 | ❌ FAIL |
| Integration tests | 0 | > 0 | ❌ FAIL |

**Recommendations:**
1. Add integration tests for full scoring pipeline
2. Cover calculation logic in calculator.py:79-140
3. Add tests for scoring.py entry points
4. Add adversarial tests (NaN, empty, timeout)
5. Remove or deprecate zero-coverage modules

---

## 9. Command to Verify

```bash
pytest tests/scoring/ --cov=backend/scoring --cov-report=term-missing --cov-fail-under=80
```

**Expected:** FAIL (29.4% < 80%)
