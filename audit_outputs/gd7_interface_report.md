# GĐ7 INTERFACE REPORT

**Date:** 2026-02-17  
**Gate:** Interface Consistency Gate  
**Status:** PASS  

---

## DTO

| Check | Result |
|-------|--------|
| Defined | YES |
| Frozen | YES |
| Location | `backend/scoring/dto.py` |
| Type | `@dataclass(frozen=True)` |

### ScoreResultDTO Fields
```python
@dataclass(frozen=True)
class ScoreResultDTO:
    career_id: str
    total_score: float
    components: Dict[str, float]  # {study, interest, market, growth, risk}
    rank: int
    meta: Dict[str, Any]
```

---

## Legacy Fields

| Metric | Value |
|--------|-------|
| Detected in allowed scope | 0 |
| Purged | YES |

### Removed Legacy Fields:
- `final_score` → replaced with `total_score`
- `skill_score` → removed from WeightsInput
- `confidence_score` → removed from WeightsInput (kept in UserProfile where valid)
- `legacy_score` → N/A
- `normalized_score` → N/A

### Files Modified:
- `backend/main_controller.py` - 4 occurrences replaced
- `backend/api/routers/scoring_router.py` - WeightsInput corrected
- `backend/scoring/explain/tracer.py` - `set_final_score` → `set_total_score`
- `backend/scoring/components/risk.py` - `_legacy_score` function removed
- `backend/api/routers/scoring_router_backup.py` - DELETED

---

## Tests

| Category | Pass | Fail |
|----------|------|------|
| Type Check | 5 | 0 |
| Field Presence | 6 | 0 |
| Immutability | 4 | 0 |
| Legacy Rejection | 5 | 0 |
| Boundary Validation | 7 | 0 |
| DTO Conversion | 2 | 0 |
| Engine Integration | 2 | 0 |
| **TOTAL** | **31** | **0** |

---

## Gate

| Gate | Status |
|------|--------|
| Interface Contract Tests | **PASS** |
| Legacy Field Scan | **PASS** |
| CI Pipeline Lock | **CONFIGURED** |

### CI Gate File
```
.github/workflows/ci_interface_gate.yaml
```

---

## Evidence

### Test Output
```
============================= test session starts =============================
platform win32 -- Python 3.13.7
collected 31 items
tests/interface/test_dto_contract.py ............................ [100%]
============================= 31 passed in 0.59s ==============================
```

### Created Files
1. `backend/scoring/dto.py` - Canonical DTO definition
2. `tests/interface/test_dto_contract.py` - Contract test suite
3. `tests/interface/__init__.py` - Test package init
4. `.github/workflows/ci_interface_gate.yaml` - CI merge gate

### Modified Files
1. `backend/scoring/engine.py` - Added `rank_dto()` and `rank_careers_dto()`
2. `backend/main_controller.py` - Replaced `final_score` with `total_score`
3. `backend/api/routers/scoring_router.py` - Fixed WeightsInput fields
4. `backend/scoring/explain/tracer.py` - Renamed `set_final_score` to `set_total_score`
5. `backend/scoring/components/risk.py` - Removed `_legacy_score` fallback

---

## Constraints Verified

| Constraint | Status |
|------------|--------|
| No backward compatibility layer | ✓ |
| No silent remapping | ✓ |
| No monkey patch | ✓ |
| No Optional score fields | ✓ |
| No dynamic attributes | ✓ |

---

## Summary

**GĐ7 — PASS**

All interface consistency requirements met:
- ScoreResultDTO defined and frozen
- All outputs can use ScoreResultDTO via `rank_dto()` and `rank_careers_dto()`
- Legacy fields purged from allowed scope
- 31/31 tests passing
- CI gate configured for merge protection
