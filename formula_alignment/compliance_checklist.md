# Formula Alignment Compliance Checklist
## Pre-Deployment Verification

Use this checklist before any deployment to ensure formula alignment compliance.

---

## Pre-Flight Checks

### 1. Formula Source
- [ ] `ScoringFormula.compute()` is the ONLY place formula is computed
- [ ] No files contain shadow formulas (manual score aggregation)
- [ ] All scoring modules delegate to `ScoringFormula`

### 2. Component Alignment  
- [ ] SIMGR components: `study`, `interest`, `market`, `growth`, `risk`
- [ ] Controller uses correct field names (not `skill_score`, `confidence_score`)
- [ ] API responses use `ScoringFormula.WEIGHT_KEYS`

### 3. Weight Access
- [ ] All weight loading goes through `WeightsRegistry`
- [ ] No hardcoded weights in source code
- [ ] Training lineage verified at load time

### 4. Formula Verification
- [ ] Boot verification passes (`_verify_spec_at_boot()`)
- [ ] Unit tests pass (`pytest tests/scoring/test_formula.py -v`)
- [ ] Consistency tests pass (`pytest tests/scoring/test_formula_consistency.py -v`)

### 5. Risk Sign Convention
- [ ] Risk is SUBTRACTED (sign = -1)
- [ ] Higher risk = lower score (monotonicity verified)
- [ ] Risk weight is positive (subtraction handled in formula)

---

## Scan Commands

### Check for shadow formulas
```bash
# Should return no matches in production code
grep -r "total_score\s*=.*+.*\*" backend/scoring/*.py --include="*.py"
grep -r "skill_score\|confidence_score" backend/main_controller.py
```

### Run formula tests
```bash
pytest tests/scoring/test_formula.py -v
pytest tests/scoring/test_formula_consistency.py -v -m "not slow"
```

### Verify boot check
```bash
python -c "from backend.scoring.scoring_formula import ScoringFormula; print('Boot OK')"
```

---

## Violation Resolution

### If shadow formula detected:
1. Identify the file and line number
2. Replace direct computation with `ScoringFormula.compute()`
3. Add test to verify delegation
4. Update this checklist

### If component mismatch found:
1. Map old names to SIMGR names:
   - `skill_score` → `study_score`
   - `confidence_score` → `risk_score` (in breakdowns)
2. Verify UserProfile fields are NOT changed (they're user input)
3. Test API response format

---

## Sign-Off

| Check | Reviewer | Date |
|-------|----------|------|
| Shadow Scan | | |
| Component Alignment | | |
| Weight Registry | | |
| Boot Verification | | |
| Unit Tests | | |

---

*Last updated: 2026-02-16*
