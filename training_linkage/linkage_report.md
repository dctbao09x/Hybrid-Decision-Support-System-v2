# Training Linkage Report — GĐ5 Phase B-I

**Date**: 2026-02-16  
**Phase**: GIAI ĐOẠN 5 — Training ↔ Runtime Linkage (Extended)  
**Status**: ✅ IMPLEMENTED

---

## Summary

This report documents the implementation of training ↔ runtime linkage enforcement per sections IV-XII of the GĐ5 specification.

**Core Principle**: Runtime CHỈ chạy với trained model. Zero Orphan Model.

---

## I. Components Implemented

### PHẦN B — Training Side Integration

**File**: `backend/training/train_weights.py`

| Feature | Status | Implementation |
|---------|--------|----------------|
| Auto generate metadata | ✅ | `create_weight_artifact()` called in `save_weights()` |
| Auto hash | ✅ | `compute_weights_checksum()` for weights, `compute_file_checksum()` for dataset |
| Auto log commit | ✅ | `get_git_commit()` captures trainer commit |
| Validate R² threshold | ✅ | `_validate_quality_thresholds()` checks R² >= 0.7 |
| Validate MAE threshold | ✅ | `_validate_quality_thresholds()` checks MAE <= 0.1 |
| Fail on unqualified | ✅ | `TrainingQualityError` raised, model NOT exported |

**New Config**:
```python
@dataclass
class TrainingConfig:
    min_r2: float = 0.7       # R² >= 0.7 required  
    max_mae: float = 0.1      # MAE <= 0.1 required
    enforce_thresholds: bool = True
```

---

### PHẦN C — Runtime Linker

**File**: `backend/scoring/training_linker.py`

```python
class TrainingLinker:
    MAX_AGE_DAYS = 90
    
    @classmethod
    def load_verified_weights(cls) -> SIMGRWeights:
        """THE ONLY gateway for runtime weights."""
```

**Verification Pipeline** (8 steps):
1. Load weights.json
2. Load weight_metadata.json
3. Verify checksum
4. Verify freshness (90 days)
5. Verify features
6. Verify metrics thresholds
7. Verify trainer_commit
8. Check manual override

---

### PHẦN D — Runtime Enforcement

**Rules Enforced**:
- ❌ CẤM: Load weights.json trực tiếp
- ❌ CẤM: Default fallback
- ❌ CẤM: Hardcoded weights

**Enforcement**: All violations raise `ModelIntegrityError` → Abort scoring.

---

### PHẦN E — Staleness & Tamper Detection

| Condition | Error | Description |
|-----------|-------|-------------|
| `now - trained_at > 90 days` | `StaleModelError` | STALE_MODEL |
| Checksum mismatch | `TamperedModelError` | TAMPERED_MODEL |
| Missing metadata | `InvalidModelError` | INVALID_MODEL |
| R² < 0.7 or MAE > 0.1 | `UnqualifiedModelError` | UNQUALIFIED_MODEL |

---

### PHẦN F — Manual Override Blocking

**File**: `backend/scoring/promote_model.py`

**Detection Mechanisms**:
- `weights.json` mtime > metadata mtime → REJECT
- Missing `trainer_commit` → REJECT
- No audit log → REJECT

**Approved Promotion Path**:
```bash
python -m backend.scoring.promote_model v2 --user "data_scientist" --reason "Improved R²"
```

**Audit Log**: `logs/model_promotion_audit.jsonl`

---

### PHẦN G — Traceability Header

**File**: `backend/scoring/lineage_validator.py`

Every API response MUST include:
```json
{
  "model_lineage": {
    "weight_version": "v3",
    "trained_at": "2026-02-15T10:30:00",
    "dataset": "backend/data/scoring/train.csv",
    "checksum": "abc123..."
  }
}
```

**Usage**:
```python
from backend.scoring.lineage_validator import add_lineage_to_response

response = {"score": 0.85}
response = add_lineage_to_response(response)
# Response now has model_lineage
```

---

### PHẦN H — Test Suite

**File**: `backend/scoring/tests/test_training_linkage.py`

| Test Class | Description |
|------------|-------------|
| `TestValidModelLoad` | Valid model loads successfully |
| `TestMissingMetadataReject` | Missing metadata → REJECT |
| `TestStaleModelReject` | Age > 90 days → REJECT |
| `TestChecksumMismatch` | Modified weights → REJECT |
| `TestManualOverrideBlocked` | Missing commit → REJECT |
| `TestMetricThreshold` | R² < 0.7 or MAE > 0.1 → REJECT |
| `TestLineageHeader` | Response has model_lineage |

**Run**:
```bash
pytest backend/scoring/tests/test_training_linkage.py -v
```

---

### PHẦN I — Output Artifacts

```
training_linkage/
├── training_linker.py        → Link to backend/scoring/training_linker.py
├── weight_metadata.schema.json
├── lineage_validator.py      → Link to backend/scoring/lineage_validator.py
├── promote_model.py          → Link to backend/scoring/promote_model.py
├── linkage_report.md         (this file)
└── compliance.json
```

---

## II. Gate Criteria

| Criterion | Status |
|-----------|--------|
| ✓ Runtime chỉ chạy với trained model | PASS |
| ✓ Manual override bị chặn | PASS |
| ✓ Metadata đầy đủ | PASS |
| ✓ Lineage trace OK | PASS |
| ✓ Tests pass | PENDING |
| ✓ No fallback | PASS |

---

## III. Usage Guide

### Loading Weights at Runtime

```python
from backend.scoring.training_linker import TrainingLinker

# This is the ONLY approved way
weights = TrainingLinker.load_verified_weights()

# Get lineage for response
lineage = TrainingLinker.get_lineage_header()
```

### Running Training

```python
from backend.training.train_weights import SIMGRWeightTrainer, TrainingConfig

config = TrainingConfig(
    version="v2",
    min_r2=0.7,
    max_mae=0.1,
    enforce_thresholds=True,  # Fail if metrics don't meet threshold
)

trainer = SIMGRWeightTrainer(config)
trainer.train()  # Will fail if R² < 0.7 or MAE > 0.1
```

### Promoting Models

```bash
# Via CLI
python -m backend.scoring.promote_model v2 --user "admin" --reason "Higher accuracy"

# Via code
from backend.scoring.promote_model import ModelPromoter

promoter = ModelPromoter()
promoter.promote("v2", user="admin", reason="Higher accuracy")
```

---

## IV. Final Rules

1. **Không trust file system** — Always verify checksum
2. **Không trust config** — Always verify metadata
3. **Chỉ trust verified artifact** — TrainingLinker is the only gateway
4. **Không exception cho dev** — STRICT mode everywhere
5. **Zero Orphan Model** — Every model has full lineage

---

## V. Files Summary

| File | Location | Purpose |
|------|----------|---------|
| training_linker.py | backend/scoring/ | Runtime weight loading |
| promote_model.py | backend/scoring/ | Controlled promotion |
| lineage_validator.py | backend/scoring/ | Response lineage |
| train_weights.py | backend/training/ | Training with thresholds |
| weight_metadata.py | backend/scoring/ | Metadata schema |
| weights_registry.py | backend/scoring/ | Registry pattern |
| test_training_linkage.py | backend/scoring/tests/ | Test suite |

---

**Implementation Complete**: Runtime ↔ Training linkage fully enforced.
