# SIMGR Formula Alignment Report
## GĐ4 Extended - Zero Formula Drift

**Generated:** 2026-02-16
**Version:** v1.0
**Status:** ✅ COMPLIANT

---

## Executive Summary

This report documents the formula alignment audit performed for the SIMGR scoring system. The goal is **Zero Formula Drift** - ensuring only ONE formula source exists.

### Canonical Formula
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
```

Where:
- **wS, wI, wM, wG, wR** = weights (must sum to 1.0)
- **S** = Study score [0, 1]
- **I** = Interest score [0, 1]
- **M** = Market score [0, 1]
- **G** = Growth score [0, 1]
- **R** = Risk score [0, 1] - **SUBTRACTED**

---

## PHẦN A+B: Shadow Formula Scan

### Scan Results

| File | Status | Notes |
|------|--------|-------|
| `backend/scoring/calculator.py` | ✅ COMPLIANT | Delegates to `ScoringFormula.compute()` |
| `backend/scoring/scoring.py` | ✅ COMPLIANT | Uses `ScoringFormula.compute()` at line 235 |
| `backend/scoring/scoring_formula.py` | ✅ SOURCE | Single source of truth |

### Forbidden Patterns Checked
- `total_score = ... + ... * score` - No violations
- `final_score = ... study ... interest` - No violations  
- `score += ... weight` - No violations in production code

### Files with Formula Documentation (OK)
Some files contain formula in comments for documentation purposes. This is acceptable:
- `backend/scoring/scoring_formula.py` - Official spec documentation
- `tests/scoring/test_formula.py` - Test documentation

---

## PHẦN C: Controller Alignment

### Violations Fixed

The following field name mismatches were corrected in `main_controller.py`:

| Line | Before | After |
|------|--------|-------|
| 415-423 | `skill_score`, `confidence_score` | `study_score`, `risk_score` |
| 490-497 | `skill_score`, `confidence_score` | `study_score`, `risk_score` |
| 519-527 | `skill_score`, `confidence_score` | `study_score`, `risk_score` |
| 553-561 | `skill_score`, `confidence_score` | `study_score`, `risk_score` |

### Note on UserProfile
`UserProfile.confidence_score` remains unchanged - it represents user's self-assessed confidence (input field), NOT a SIMGR component.

---

## PHẦN D: Weight Registry Access

### Verification

✅ **COMPLIANT** - Weight loading follows the chain:

```
SIMGRWeights.from_file()
    ↓
WeightsRegistry.load_active_weights()
    ↓
Training lineage validation
    ↓
Metadata checksum verification
    ↓
Weights returned
```

**Key Files:**
- `backend/scoring/config.py` - Uses `get_registry()` for all weight loading
- `backend/scoring/weights_registry.py` - Enforces training linkage

---

## PHẦN E: Spec Self-Verification at Boot

### Implementation

Added to `backend/scoring/scoring_formula.py`:

```python
DOC_SPEC_FORMULA = "Score = wS*S + wI*I + wM*M + wG*G - wR*R"
DOC_SPEC_COMPONENTS = ["study", "interest", "market", "growth", "risk"]
DOC_SPEC_VERSION = "v1.0"

def _verify_spec_at_boot() -> None:
    assert ScoringFormula.get_formula() == DOC_SPEC_FORMULA
    assert ScoringFormula.get_components() == DOC_SPEC_COMPONENTS
    assert ScoringFormula.get_version() == DOC_SPEC_VERSION
    assert ScoringFormula.get_sign("risk") == -1

# Run at import time
_verify_spec_at_boot()
```

This ensures any formula drift is caught immediately at runtime startup.

---

## PHẦN F: Unit Tests

### Test Files Created/Updated

1. **`tests/scoring/test_formula.py`** - Extended with:
   - `TestScoringFormulaCompute` - Tests `ScoringFormula.compute()`
   - `TestFormulaBootVerification` - Tests boot verification
   - `TestAllModulesUseScoringFormula` - Verifies delegation

2. **`tests/scoring/test_formula_consistency.py`** - NEW:
   - Grid-based consistency tests
   - Tolerance verification (≤ 1e-6)
   - Risk sign monotonicity tests

### Key Test Cases

| Test | Purpose |
|------|---------|
| `test_scoring_formula_compute_basic` | Basic formula computation |
| `test_scoring_formula_subtracts_risk` | Risk MUST be subtracted |
| `test_scoring_formula_clamping` | Output clamped to [0,1] |
| `test_scoring_formula_validation_missing_component` | Reject incomplete input |
| `test_boot_verification_runs` | Boot check works |
| `test_calculator_uses_scoring_formula` | Delegation verified |

---

## PHẦN G: Inference Consistency Check

### Grid Test Configuration

```python
TOLERANCE = 1e-6
GRID_STEP = 0.1
GRID_VALUES = [0.0, 0.1, 0.2, ..., 1.0]  # 11 values
```

### Test Coverage

| Test | Combinations | Weights |
|------|--------------|---------|
| `test_grid_corners_equal_weights` | 32 (2^5) | Equal (0.2 each) |
| `test_grid_corners_trained_weights` | 32 (2^5) | Trained (variable) |
| `test_grid_midpoints` | 243 (3^5) | Equal |
| `test_full_grid_equal_weights` | 161,051 (11^5) | Equal |

### Reference Formula

```python
def expected_formula(scores, weights):
    return (
        weights["study"] * scores["study"]
        + weights["interest"] * scores["interest"]
        + weights["market"] * scores["market"]
        + weights["growth"] * scores["growth"]
        - weights["risk"] * scores["risk"]
    )
```

---

## PHẦN H: Output Artifacts

### Files Created

```
formula_alignment/
├── formula_schema.json      # JSON Schema for validation
├── formula_spec.json        # Current spec as data
├── FORMULA_ALIGNMENT_REPORT.md  # This document
└── compliance_checklist.md  # Pre-flight checklist
```

---

## Compliance Summary

| Requirement | Status |
|-------------|--------|
| Single formula source | ✅ `ScoringFormula.compute()` |
| Risk subtracted | ✅ Verified |
| Weight sum = 1.0 | ✅ Validated |
| Scores in [0,1] | ✅ Clamped |
| No shadow formulas | ✅ Scanned |
| Controller aligned | ✅ Fixed |
| Boot verification | ✅ Added |
| Unit tests | ✅ Extended |
| Grid consistency | ✅ Created |

---

## Recommendations

1. **CI Integration**: Add `test_formula.py` and `test_formula_consistency.py` to CI pipeline
2. **Pre-commit Hook**: Add shadow formula scan as pre-commit check
3. **Documentation**: Update API docs to reference `formula_spec.json`

---

*Document generated by GĐ4 Extended Formula Alignment process*
