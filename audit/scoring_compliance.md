# Scoring System Governance Compliance Report
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** Code-only analysis (no documentation, no comments, no assumptions)

---

## Executive Summary

| Area | Status | Severity |
|------|--------|----------|
| 1. Formula Verification | ✅ PASS | - |
| 2. Weight Governance | ⚠️ CONDITIONAL | MEDIUM |
| 3. Component Traceability | ✅ PASS | - |
| 4. Data Pipeline Integrity | ⚠️ CONDITIONAL | HIGH |
| 5. Training Pipeline | ✅ PASS | - |
| 6. Bypass & Attack Surface | ❌ FAIL | HIGH |
| 7. Controller Integrity | ⚠️ CONDITIONAL | MEDIUM |
| 8. Error Governance | ❌ FAIL | HIGH |
| 9. Test Coverage | ❌ FAIL | CRITICAL |

---

## 1. Formula Verification

**Status:** ✅ **PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Runtime formula | `Score = wS*S + wI*I + wM*M + wG*G - wR*R` | calculator.py:102-110 |
| Risk subtraction | ✅ VERIFIED | Line 108: `- wR*R` |
| Boundary handling | ✅ VERIFIED | normalizer.clamp() for [0,1] |
| Numeric validation | ✅ VERIFIED | Manual calc matches runtime |

**Artifact:** [scoring_formula_audit.md](scoring_formula_audit.md)

---

## 2. Weight Governance

**Status:** ⚠️ **CONDITIONAL PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Default weights | ✅ DEFINED | config.py:30-34 |
| Trained weights | ✅ EXIST | models/weights/v1/weights.json |
| Weight loading | ✅ IMPLEMENTED | SIMGRWeights.from_file() |
| Fallback logic | ⚠️ EXISTS | Falls back to hardcoded defaults |
| Hot reload | ✅ IMPLEMENTED | ScoringConfig.reload() |
| Hardcoded bypass | ⚠️ YES | Default weights always available |

**Issues:**
1. Training can be bypassed by not providing weights file
2. Hardcoded defaults in SIMGRWeights dataclass

**Artifact:** Weight chain traced in [component_trace.json](component_trace.json)

---

## 3. Component Traceability

**Status:** ✅ **PASS**

| Component | Entry | Formula | Factors | Data Source |
|-----------|-------|---------|---------|-------------|
| Study | study.py:140 | S = 0.4A + 0.3B + 0.3C | ability, background, confidence | user input |
| Interest | interest.py:152 | I = 0.4NLP + 0.3Survey + 0.3Stability | nlp, survey, stability | user input |
| Market | market.py:119 | M = 0.3AI + 0.3Growth + 0.2Salary + 0.2InvComp | ai, growth, salary, competition | cache/input |
| Growth | growth.py:194 | G = 0.35Demand + 0.35Salary + 0.30Lifecycle | demand, salary_growth, lifecycle | hardcoded datasets |
| Risk | risk.py:227 | R = weighted 6-factor | saturation, obsolescence, etc. | hardcoded datasets |

**Artifact:** [component_trace.json](component_trace.json)

---

## 4. Data Pipeline Integrity

**Status:** ⚠️ **CONDITIONAL PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Input validation | ✅ PASS | Pydantic models |
| Output validation | ✅ PASS | normalizer.clamp() |
| Cache mechanism | ✅ EXISTS | MarketCacheLoader |
| Versioning | ⚠️ PARTIAL | Only weights versioned |
| Silent failures | ❌ FAIL | Dataset fallbacks not surfaced |
| Missing data | ❌ FAIL | unemployment/rates.csv, cost dataset |

**Issues:**
1. `data/risk/unemployment/rates.csv` NOT FOUND
2. Cost dataset parsing FAILED
3. Silent fallback to hardcoded dictionaries

**Artifact:** [data_integrity_report.md](data_integrity_report.md)

---

## 5. Training Pipeline

**Status:** ✅ **PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Training script | ✅ EXISTS | backend/training/train_weights.py |
| Dataset | ✅ EXISTS | backend/data/scoring/train.csv (50 rows) |
| Features | ✅ CORRECT | study, interest, market, growth, risk |
| Label | ✅ CORRECT | outcome |
| Version control | ✅ EXISTS | models/weights/v1/, models/weights/active/ |
| Deployment | ✅ EXISTS | weights.json versioned |

**Usage:** Training is **OPTIONAL**. System can run without trained weights.

---

## 6. Bypass & Attack Surface

**Status:** ❌ **FAIL**

| Attack Vector | Blocked? | Evidence |
|---------------|----------|----------|
| Direct calculator import | ❌ NO | `from backend.scoring.calculator import SIMGRCalculator` works |
| Direct engine import | ❌ NO | `from backend.scoring.engine import RankingEngine` works |
| Direct component import | ❌ NO | All components publicly importable |
| Config injection | ❌ NO | Any weights accepted |
| Component map mutation | ❌ NO | component_map is mutable dict |
| API auth | ✅ YES | middleware/auth.py enforced |
| RBAC | ✅ YES | middleware/rbac.py enforced |

**Finding:** All scoring classes publicly importable. No module-level access control.

**Artifact:** [bypass_surface.md](bypass_surface.md)

---

## 7. Controller Integrity

**Status:** ⚠️ **CONDITIONAL PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Single entry | ✅ YES | API → controller.dispatch() |
| No skip paths | ✅ YES | All layers traversed |
| No parallel scoring | ✅ YES | Single engine per request |
| No legacy path | ✅ YES | No legacy scoring endpoints |
| Field consistency | ❌ FAIL | breakdown fields mismatch |

**Issue:** API expects `skill_score`, `confidence_score` but calculator produces `growth_score`, `risk_score`.

**Artifact:** [control_flow_map.md](control_flow_map.md)

---

## 8. Error Governance

**Status:** ❌ **FAIL**

| Failure Mode | Handled? | Silent? |
|--------------|----------|---------|
| Missing field | ✅ YES | ❌ NO |
| None/NaN/Inf | ✅ YES | ✅ YES |
| Missing dataset | ⚠️ PARTIAL | ✅ YES |
| Component crash | ⚠️ PARTIAL | ✅ YES |
| Timeout | ❌ NO | N/A |

**Issues:**
1. Silent fallback to 0.5 on component failure
2. Missing dataset doesn't surface to user
3. No timeout handling in scoring path

**Artifact:** [failure_matrix.md](failure_matrix.md)

---

## 9. Test Coverage

**Status:** ❌ **FAIL**

| Metric | Value | Threshold |
|--------|-------|-----------|
| Overall coverage | **29.4%** | 80% |
| Tests passing | 112 | - |
| Zero-coverage modules | 5 | 0 |
| Integration tests | 0 | > 0 |

**Finding:** Coverage 29.4% is well below 80% threshold.

**Artifact:** [coverage_report.md](coverage_report.md)

---

## FINAL VERDICT

# ❌ **FAIL**

---

## Justification (Evidence Only)

| Rule | Violated? | Evidence |
|------|-----------|----------|
| Any undocumented fallback | ✅ YES | Component failure → 0.5 (not documented in response) |
| Any bypass | ✅ YES | All scoring classes publicly importable |
| Any silent default | ✅ YES | Missing datasets → hardcoded fallback (logged only) |
| Any unused training | ❌ NO | Training pipeline exists and produces weights |

### Specific Violations

1. **Bypass (CRITICAL)**
   - `SIMGRCalculator`, `RankingEngine`, `SIMGRScorer` all importable without auth
   - Evidence: `from backend.scoring.calculator import SIMGRCalculator` succeeds

2. **Silent Fallback (HIGH)**
   - Component failures masked by 0.5 neutral score
   - Evidence: calculator.py:96 `simgr_scores[component_name] = 0.5`

3. **Silent Default (HIGH)**
   - Missing unemployment/cost datasets use hardcoded defaults
   - Evidence: Runtime log "Unemployment dataset not found" but score returned normally

4. **Coverage (CRITICAL)**
   - 29.4% < 80% threshold
   - Evidence: pytest-cov output

---

## Artifacts Generated

| Artifact | Purpose |
|----------|---------|
| [scoring_formula_audit.md](scoring_formula_audit.md) | Formula verification |
| [component_trace.json](component_trace.json) | Component traceability |
| [bypass_surface.md](bypass_surface.md) | Attack surface analysis |
| [data_integrity_report.md](data_integrity_report.md) | Data pipeline integrity |
| [control_flow_map.md](control_flow_map.md) | Controller flow tracing |
| [failure_matrix.md](failure_matrix.md) | Error governance testing |
| [coverage_report.md](coverage_report.md) | Test coverage analysis |
| [scoring_compliance.md](scoring_compliance.md) | This document |

---

*This audit was conducted using code evidence only. No documentation was consulted. No assumptions were made.*
