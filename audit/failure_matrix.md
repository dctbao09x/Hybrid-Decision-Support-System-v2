# Failure Matrix
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** Error injection testing

---

## 1. Failure Injection Tests

### Test 1: Missing Required Fields

**Injection:**
```python
career = CareerData()  # Missing required 'name' field
```

**Result:**
```
ValidationError: 1 validation error for CareerData
name
  Field required [type=missing]
```

**Behavior:** ❌ **EXCEPTION** - Pydantic raises ValidationError
**Propagation:** Exception propagates to caller
**User-Facing:** Returns HTTP 422 Unprocessable Entity

---

### Test 2: None Fields

**Injection:**
```python
user = UserProfile(skills=None, interests=None)
career = CareerData(name='Test')
calc.calculate(user, career)
```

**Result:** ✅ **GRACEFUL** - Calculator handles None gracefully
**Behavior:** None converted to empty set internally
**User-Facing:** Normal score returned

---

### Test 3: Empty Data

**Injection:**
```python
user = UserProfile(skills=[], interests=[])
career = CareerData(name='Unknown Career')
calc.calculate(user, career)
```

**Result:** ✅ **GRACEFUL** - Returns valid score
**Output:**
```
Score: 0.3404
Breakdown: {
    'study_score': 0.605,
    'interest_score': 0.18,
    'market_score': 0.52,
    'growth_score': 0.5122,
    'risk_score': 0.6269
}
```

**Behavior:** Falls back to hardcoded datasets
**User-Facing:** Normal response with fallback data

---

### Test 4: NaN/Inf Injection

**Injection:**
```python
normalizer.clamp(float('nan'))
normalizer.clamp(float('inf'))
normalizer.clamp(float('-inf'))
```

**Result:**
```
clamp(NaN) → 0.0
clamp(+Inf) → 1.0
clamp(-Inf) → 0.0
```

**Behavior:** ✅ **GRACEFUL** - All edge values handled
**User-Facing:** Normal score (clamped value)

---

### Test 5: Missing External Dataset

**Injection:** (Natural - file doesn't exist)
```
data/risk/unemployment/rates.csv → NOT FOUND
```

**Result:**
```
WARNING: Unemployment dataset not found: data/risk/unemployment/rates.csv
```

**Behavior:** ⚠️ **SILENT FALLBACK** - Uses UNEMPLOYMENT_RISK_DATASET dict
**User-Facing:** Normal response (fallback data used)
**Issue:** User unaware of degraded data quality

---

### Test 6: Corrupt Dataset

**Injection:** (Natural - parsing error)
```
Cost dataset contains non-numeric value 'variable'
```

**Result:**
```
ERROR: Failed to load cost dataset: could not convert string to float: 'variable'
```

**Behavior:** ⚠️ **SILENT FALLBACK** - Uses COST_RISK_DATASET dict
**User-Facing:** Normal response (fallback data used)
**Issue:** User unaware of data quality issue

---

### Test 7: Component Failure

**Injection:** (Simulated - component throws exception)
```python
# In calculator.py:93-96
except Exception as e:
    logger.exception(f"Component {component_name} failed: {e}")
    simgr_scores[component_name] = 0.5
    details[f"{component_name}_details"] = {"error": str(e), "fallback": True}
```

**Behavior:** ⚠️ **SILENT FALLBACK** - Component returns 0.5
**User-Facing:** Normal response with fallback in meta
**Issue:** Error masked by neutral 0.5 score

---

### Test 8: Timeout (Not Implemented)

**Finding:** No timeout handling detected in scoring path.

**Evidence:**
- `calculator.calculate()` has no timeout
- `components/*.score()` have no timeout
- `strategies.score_one()` has no timeout

**Risk:** Long-running component could block indefinitely

---

### Test 9: Empty Response (Engine)

**Injection:**
```python
engine.rank(user, careers=[])
```

**Result:** Returns empty list `[]`
**Behavior:** ✅ **GRACEFUL** - Valid empty response
**User-Facing:** Empty ranked_careers array

---

## 2. Error Propagation Matrix

| Error Type | Detection | Handling | Propagation | User-Facing |
|------------|-----------|----------|-------------|-------------|
| Missing field | Pydantic | Exception | ✅ Yes | HTTP 422 |
| None field | Component | Silent convert | ❌ No | Normal response |
| Empty data | Component | Fallback dict | ❌ No | Normal response |
| NaN/Inf | Normalizer | Clamp | ❌ No | Clamped value |
| Missing dataset | File check | Fallback dict | ⚠️ Logged only | Normal response |
| Corrupt dataset | Parse error | Fallback dict | ⚠️ Logged only | Normal response |
| Component crash | try/except | Use 0.5 | ⚠️ Meta only | Normal response |
| Timeout | **NONE** | **NONE** | **NONE** | Hang |

---

## 3. Silent Fallback Analysis

### Fallbacks Detected

| Scenario | Fallback Value | Logged? | In Response? |
|----------|----------------|---------|--------------|
| Component fails | 0.5 | ✅ Yes | ⚠️ In meta only |
| Dataset missing | Dict default | ✅ Yes | ❌ No |
| Dataset corrupt | Dict default | ✅ Yes | ❌ No |
| Market cache miss | Input fields | ✅ Yes | ⚠️ In meta only |
| Unknown career | 0.5 / default | ❌ No | ❌ No |

### Finding: **SILENT DEFAULTS EXIST**

Multiple scenarios silently use fallback values without:
1. Raising exceptions
2. Warning in API response
3. Degradation signal to user

---

## 4. Failure Matrix Summary

| Failure Mode | Handled? | Silent? | Recommendation |
|--------------|----------|---------|----------------|
| Validation error | ✅ Yes | ❌ No | OK |
| None/NaN/Inf | ✅ Yes | ✅ Yes | OK (by design) |
| Empty input | ✅ Yes | ✅ Yes | Add warning |
| Missing dataset | ⚠️ Partial | ✅ Yes | Fail or warn |
| Corrupt dataset | ⚠️ Partial | ✅ Yes | Fail or warn |
| Component crash | ⚠️ Partial | ✅ Yes | Add degraded flag |
| Timeout | ❌ No | N/A | Implement timeout |
| Empty response | ✅ Yes | ❌ No | OK |

---

## 5. Verdict

**FAILURE MATRIX: FAIL**

**Critical Issues:**
1. **Silent fallbacks** mask data quality issues
2. **No timeout handling** in scoring path
3. **Component failures** masked by 0.5 neutral score
4. **Missing datasets** don't surface to user

**Mitigating Factors:**
- Pydantic validation catches malformed input
- Normalizer handles edge numeric values
- Errors are logged (but not in response)

**Recommendations:**
1. Add `data_quality: degraded` flag to response
2. Implement component-level timeouts
3. Reference missing datasets should fail, not silently fallback
4. Add health check for required datasets
