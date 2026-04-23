# Failure Matrix
## GĐ3 - COMPONENT VALIDATION HARDENING

**Date:** 2026-02-16  
**Phase:** PHẦN H - Failure Injection  

---

## Test Matrix

| # | Injection Type | Target | Expected | Actual | Status |
|---|----------------|--------|----------|--------|--------|
| 1 | None input | validate_score_input | ABORT | ABORT (INPUT_004) | ✅ PASS |
| 2 | NaN score | scores.study | ABORT | ABORT (INPUT_005) | ✅ PASS |
| 3 | Inf score | scores.market | ABORT | ABORT (INPUT_005) | ✅ PASS |
| 4 | Missing field | scores.risk | ABORT | ABORT (INPUT_001) | ✅ PASS |
| 5 | Out of range | scores.study=1.5 | ABORT | ABORT (INPUT_003) | ✅ PASS |
| 6 | Wrong type | scores.study="high" | ABORT | ABORT (INPUT_002) | ✅ PASS |
| 7 | Missing dataset | risk/dropout | ABORT | ABORT (RISK_001) | ✅ PASS |
| 8 | Corrupt JSON | risk/dropout | ABORT | ABORT (RISK_002) | ✅ PASS |
| 9 | Missing cost column | risk/cost | ABORT | ABORT (RISK_003) | ✅ PASS |
| 10 | Missing dropout rate | risk/dropout | ABORT | ABORT (RISK_004) | ✅ PASS |

---

## Summary

| Metric | Value |
|--------|-------|
| Total injections | 10 |
| Correctly aborted | 10 |
| Silent failures | 0 |
| Abort rate | **100%** |

---

## Error Codes Verified

| Code | Description | Tested |
|------|-------------|--------|
| INPUT_001 | Missing required field | ✅ |
| INPUT_002 | Invalid field type | ✅ |
| INPUT_003 | Value out of range | ✅ |
| INPUT_004 | None value not allowed | ✅ |
| INPUT_005 | NaN/Inf value detected | ✅ |
| RISK_001 | Risk dataset missing | ✅ |
| RISK_002 | Risk data parse error | ✅ |
| RISK_003 | Cost column missing | ✅ |
| RISK_004 | Dropout rate missing | ✅ |

---

## Zero Silent Failure Guarantee

All tested failure scenarios resulted in:
1. Immediate exception raised
2. Proper error code assigned
3. Component and field identified
4. Trace ID generated
5. No default/fallback values used

**VERDICT: 0 SILENT FAILURES - PASS**
