# BASELINE FREEZE & TRACE LOCK REPORT

**Date**: 2026-02-16  
**Auditor**: Principal System Auditor  
**System**: SIMGR Scoring Engine  
**Status**: ✅ PASS - Baseline FAIL state locked  

---

## Executive Summary

Baseline freeze successfully completed. System locked at known FAIL state with 3 failing tests. All artifacts captured and verified for future audit comparisons.

---

## File Manifest

| File | Purpose | SHA256 (first 16) |
|------|---------|-------------------|
| `baseline_git_state.txt` | Git commit/branch/tag info | `2E8DEB52A55DDFE8` |
| `baseline_weights.json` | Active scoring weights | `B3A510F1E76E22B7` |
| `baseline_config_snapshot.json` | Full config dump | `19446C3FF95CF55A` |
| `baseline_runtime.log` | DEBUG scoring execution log | `15937A0AD920C937` |
| `baseline_coverage.txt` | pytest coverage output | `77984DEBF1F27B00` |
| `baseline_snapshot.json` | Combined snapshot | `E42C37E4CB59AAD0` |
| `replay_verification.json` | Verification results | `81A0B78F9906EBE1` |

---

## PHẦN A — Git Baseline Freeze

```
Commit: 156b70eeb9a116a1d7efe7edb23cecf31abf4bcd
Branch: master
Tag: scoring_baseline_fail
Dirty: YES (325 files)
```

**Verification**: `git show scoring_baseline_fail --oneline`

---

## PHẦN B — Weight Snapshot

**Source**: `models/weights/active/weights.json`

```json
{
  "study_score": 0.25,
  "interest_score": 0.25,
  "market_score": 0.25,
  "growth_score": 0.15,
  "risk_score": 0.10
}
```

**Formula**: `SIMGR = S*0.25 + I*0.25 + M*0.25 + G*0.15 - R*0.10`

---

## PHẦN C — Config Snapshot

**Source**: `config/scoring.yaml`

| Component | Value |
|-----------|-------|
| study_factors.ability_weight | 0.4 |
| study_factors.background_weight | 0.3 |
| study_factors.confidence_weight | 0.3 |
| interest_factors.nlp_weight | 0.4 |
| interest_factors.survey_weight | 0.3 |
| market_factors.ai_relevance_weight | 0.3 |
| market_factors.growth_rate_weight | 0.3 |
| risk_factors.saturation_weight | 0.25 |
| thresholds.relevance_threshold | 0.3 |
| features.deterministic | true |

**Environment Variables**: None scoring-related found.

---

## PHẦN D — Runtime Log Capture

**Log Lines**: 74  
**Test Input**: 3 skills, 2 interests, 5 careers

**Key Observations**:
```
✅ Weights loaded: models/weights/active/weights.json (version: v1)
✅ Config loaded: config\scoring.yaml
✅ Ranking complete | returned=5
⚠️ Market cache miss (all careers)
❌ Unemployment dataset not found: data/risk/unemployment/rates.csv
❌ Cost dataset parse error: 'variable'
```

**Scoring Results**:
```
#1: data scientist = 0.4019
#2: software engineer = 0.3616
#3: devops engineer = 0.3405
```

---

## PHẦN E — Coverage Freeze

| Metric | Value |
|--------|-------|
| Total Coverage | **40.31%** |
| Tests Passed | 99 |
| Tests Failed | 3 |
| Required | 80.0% (NOT MET) |

### Failed Tests

1. `test_rank_careers_baseline_compatibility` - Integration
2. `test_score_direct_components_valid` - Unit
3. `test_score_direct_components_custom_config` - Unit

### Low Coverage Files (< 50%)

| File | Coverage |
|------|----------|
| `config_loader.py` | 0.0% |
| `drift.py` | 0.0% |
| `scheduler.py` | 0.0% |
| `version_manager.py` | 0.0% |
| `explain/shap_engine.py` | 18.8% |
| `explain/xai.py` | 24.9% |
| `explain/reason_generator.py` | 26.2% |
| `taxonomy_adapter.py` | 42.9% |

---

## PHẦN F — Baseline Snapshot

**Location**: `baseline/baseline_snapshot.json`

Structure:
```json
{
  "timestamp": "2026-02-16T18:55:17.201584",
  "git": { "commit": "156b70eeb...", "tag": "scoring_baseline_fail" },
  "weights": { "study_score": 0.25, ... },
  "config": { "version": "1.0", ... },
  "runtime": { "total_lines": 74, ... },
  "coverage": { "total_percent": 40.31, "failed": 3 },
  "environment": { "python_version": "3.13.7", ... },
  "hashes": { ... }
}
```

---

## PHẦN G — Replay Verification

| Check | Result |
|-------|--------|
| Weights match | ✅ PASS |
| Coverage (pass/fail) match | ✅ PASS |
| Formula verified | ✅ PASS |
| Coverage tolerance (±1%) | ✅ PASS |

```
Replay passed: 99, failed: 3
Baseline passed: 99, failed: 3
```

**VERDICT**: ✅ **PASS** — Baseline FAIL state successfully reproduced.

---

## Deviations

| Issue | Severity | Impact |
|-------|----------|--------|
| Missing `data/risk/unemployment/rates.csv` | ⚠️ Medium | Risk scoring uses defaults |
| Cost dataset parse error | ⚠️ Medium | Risk scoring uses defaults |
| Market cache empty | ℹ️ Low | Uses career input fields |
| 325 dirty files in repo | ℹ️ Info | Tag created on clean commit |

---

## Conclusions

### Baseline State
- **Status**: FAIL (3 tests failing)
- **Root Cause**: Not analyzed (audit only, no fix)
- **Coverage**: 40.31% (below 80% threshold)

### Artifacts Verified
- ✅ Git tag `scoring_baseline_fail` created
- ✅ Weights snapshot captured
- ✅ Config snapshot captured  
- ✅ Runtime log captured
- ✅ Coverage captured
- ✅ Replay verification PASSED

### Audit Readiness
System is now in a **known, locked state**. Any future changes can be compared against this baseline to:
1. Detect regression
2. Verify fixes
3. Track coverage improvement
4. Audit formula changes

---

## Usage Instructions

### Compare with future state:
```bash
# Check if weights changed
diff baseline/baseline_weights.json models/weights/active/weights.json

# Re-run verification
python scripts/replay_verification.py

# Check coverage delta
pytest backend/tests/scoring --cov=backend/scoring --cov-report=term
```

### Roll back to baseline:
```bash
git checkout scoring_baseline_fail
```

---

**Report Generated**: 2026-02-16  
**Next Review**: After any scoring change
