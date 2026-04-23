# Risk Register
## SIMGR + Stage 3 Governance Audit

**Date:** 2026-02-16  
**Version:** 1.0.0

---

## Risk Summary

| ID | Risk | Severity | Likelihood | Impact | Status |
|----|------|----------|------------|--------|--------|
| R001 | Formula Violation | CRITICAL | CONFIRMED | HIGH | OPEN |
| R002 | No Weight Learning | HIGH | CONFIRMED | HIGH | OPEN |
| R003 | Static Data Staleness | HIGH | PROBABLE | MEDIUM | OPEN |
| R004 | Missing Component Factors | MEDIUM | CONFIRMED | MEDIUM | OPEN |
| R005 | Hardcoded Configurations | MEDIUM | CONFIRMED | LOW | OPEN |
| R006 | Incomplete Testing | MEDIUM | CONFIRMED | MEDIUM | OPEN |
| R007 | No Drift Detection | LOW | POSSIBLE | MEDIUM | OPEN |

---

## Detailed Risk Analysis

### R001: Formula Violation
**Description:** Scoring formula ADDS risk instead of SUBTRACTING as per DOC specification.

| Field | Value |
|-------|-------|
| Category | Functional Correctness |
| Files Affected | `calculator.py`, `scoring.py` |
| Lines | 101-107, 227-233 |
| Impact | Incorrect career rankings |
| Mitigation | Change `+` to `-` for risk term |
| Owner | Engineering |
| Due Date | Immediate |

---

### R002: No Weight Learning Pipeline
**Description:** SIMGR weights are hardcoded, not learned from data.

| Field | Value |
|-------|-------|
| Category | MLOps |
| Files Affected | `config.py` |
| Impact | Suboptimal recommendations |
| Mitigation | Implement regression training pipeline |
| Owner | ML Engineering |
| Due Date | High Priority |

---

### R003: Static Data Staleness
**Description:** Growth component uses static career data without refresh mechanism.

| Field | Value |
|-------|-------|
| Category | Data Freshness |
| Files Affected | `components/growth.py` |
| Impact | Outdated career growth information |
| Mitigation | Implement tech crawler + forecast |
| Owner | Data Engineering |
| Due Date | Medium Priority |

---

### R004: Missing Component Factors
**Description:** Study, Interest, and Risk components missing DOC-required factors.

| Component | Missing Factors |
|-----------|-----------------|
| Study | Academic (A), Test score (B) |
| Interest | NLP analyzer, Survey ingestion |
| Risk | Dropout model, Unemployment data |

---

### R005: Hardcoded Configurations
**Description:** Risk sub-weights and thresholds are hardcoded in Python code.

| Field | Value |
|-------|-------|
| Files Affected | `config.py` |
| Recommended | External YAML configuration |
| Impact | Requires code deployment for changes |

---

### R006: Incomplete Testing
**Description:** Test coverage for scoring components not verified at 85%.

| Test Type | Status |
|-----------|--------|
| Unit tests | Partial |
| Formula tests | Missing |
| Weight regression | Missing |
| Drift detection | Missing |

---

### R007: No Drift Detection
**Description:** No mechanism to detect model drift or scoring distribution changes.

| Field | Value |
|-------|-------|
| Category | MLOps/Monitoring |
| Impact | Silent degradation of recommendations |
| Mitigation | Implement drift monitoring |

---

## Risk Matrix

```
         Impact
         Low     Medium    High
   High  |       R006     R001 R002
Likely   |       R004     R003
   Low   | R005  R007     |
```

---

## Mitigation Priority

1. **Immediate:** R001 (Formula fix)
2. **High:** R002 (Weight learning)
3. **Medium:** R003, R004, R006
4. **Low:** R005, R007

---

*Risk register maintained as part of SIMGR Governance Audit.*
