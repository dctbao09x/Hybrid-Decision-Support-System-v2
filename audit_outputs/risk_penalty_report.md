# Risk Penalty Audit Report
## SIMGR + Stage 3 Full Governance Audit

**Date:** 2026-02-16  
**Auditor:** Principal System Architect  
**Status:** ❌ FAIL

---

## I. DOC REQUIREMENTS

### Required Modules:
```
risk/
├─ model.py      → Dropout/unemployment prediction
├─ penalty.py    → Penalty calculation formula
└─ config.yaml   → Configurable thresholds
```

### Required Evidence:

| Module | Evidence Required | Status |
|--------|-------------------|--------|
| Dropout | Model / rule | ❌ NOT FOUND |
| Cost | Formula | ❌ NOT FOUND |
| Unemployment | Dataset | ❌ NOT FOUND |
| Penalty | Formula | ⚠️ PARTIAL |
| Threshold | Config | ❌ NOT CONFIGURABLE |

---

## II. DIRECTORY SEARCH

### Search: `risk/` directory
```
❌ backend/risk/ - NOT FOUND
```

### Actual Location: `backend/scoring/components/risk.py`

---

## III. CURRENT IMPLEMENTATION ANALYSIS

### File: `backend/scoring/components/risk.py`

#### Risk Factors Computed:

```python
# Line 35 - Market Saturation Risk
market_saturation_risk = normalizer.clamp(job.competition)

# Line 38-40 - Skill Obsolescence Risk
skill_obsolescence_risk = normalizer.clamp(1.0 - job.growth_rate)

# Line 43-45 - Competition Risk
competition_risk = normalizer.clamp(1.0 - job.ai_relevance)
```

#### Weights (Line 28):
```python
weights = config.component_weights
# risk weights:
#   market_saturation_risk: 0.4
#   skill_obsolescence_risk: 0.3
#   competition_risk: 0.3
```

#### Formula (Lines 48-52):
```python
total_risk = (
    market_saturation_risk * weights.market_saturation_risk +
    skill_obsolescence_risk * weights.skill_obsolescence_risk +
    competition_risk * weights.competition_risk
)
```

#### Critical Inversion (Line 55):
```python
risk_score = normalizer.clamp(1.0 - total_risk)
```

---

## IV. GAP ANALYSIS

### 1. Dropout Model
| Requirement | Status |
|-------------|--------|
| Dropout prediction model | ❌ NOT IMPLEMENTED |
| Dropout rate data source | ❌ NOT FOUND |
| Dropout risk calculation | ❌ NOT FOUND |

### 2. Cost Formula
| Requirement | Status |
|-------------|--------|
| Education cost formula | ❌ NOT IMPLEMENTED |
| Time cost formula | ❌ NOT IMPLEMENTED |
| Opportunity cost formula | ❌ NOT IMPLEMENTED |

### 3. Unemployment Dataset
| Requirement | Status |
|-------------|--------|
| Unemployment rate dataset | ❌ NOT FOUND |
| Unemployment data source | ❌ NOT FOUND |
| Historical unemployment | ❌ NOT FOUND |

### 4. Penalty Formula
| Requirement | Status |
|-------------|--------|
| Penalty calculation | ⚠️ INDIRECT (via risk factors) |
| Penalty configurable | ❌ HARDCODED in code |
| Penalty threshold | ❌ NOT CONFIGURABLE |

### 5. Threshold Configuration
| Requirement | Status |
|-------------|--------|
| risk/config.yaml | ❌ NOT FOUND |
| Threshold settings | ❌ NOT FOUND |
| Dynamic threshold loading | ❌ NOT IMPLEMENTED |

---

## V. WEIGHT CONFIGURATION ANALYSIS

### File: `backend/scoring/config.py` (Lines 82-96)

```python
@dataclass
class ComponentWeights:
    # Risk component weights
    market_saturation_risk: float = 0.4   # ❌ HARDCODED
    skill_obsolescence_risk: float = 0.3  # ❌ HARDCODED
    competition_risk: float = 0.3         # ❌ HARDCODED
```

**Issue:** Risk sub-weights are **HARDCODED**, not loaded from config file.

---

## VI. FORMULA VIOLATION ANALYSIS

### DOC Formula Requirement:
```
Score = wS*S + wI*I + wM*M + wG*G - wR*R
                                  ↑↑↑
                                  SUBTRACT
```

### Actual Implementation:

#### In `calculator.py` (line 106):
```python
simgr_scores.get("risk", 0.5) * weights.risk_score
# This is ADDED, not SUBTRACTED
```

### Mathematical Issue:

Current workflow:
1. Raw risks computed (high = bad)
2. `total_risk` = weighted sum of raw risks
3. `risk_score` = 1.0 - total_risk (INVERTED)
4. Formula: Score = ... + risk_score * w_risk (ADDED)

Expanded:
```
Score = ... + (1 - total_risk) * w_risk
Score = ... + w_risk - w_risk * total_risk
```

DOC requires:
```
Score = ... - w_risk * R
```

Where R = total_risk (raw, not inverted).

**Current formula adds a constant bias (+w_risk) which is NOT per DOC specification.**

---

## VII. STRUCTURAL VIOLATIONS

| Rule | Status |
|------|--------|
| Penalty hardcode → FAIL | ⚠️ PARTIAL FAIL |
| Penalty configurable | ❌ NOT CONFIGURABLE |
| Config file exists | ❌ risk/config.yaml NOT FOUND |
| Model exists | ❌ risk/model.py NOT FOUND |
| Dataset exists | ❌ Unemployment data NOT FOUND |

---

## VIII. RECOMMENDED FIX

### 1. Create Risk Module Structure:
```
backend/risk/
├─ __init__.py
├─ model.py          # Dropout/unemployment prediction
├─ penalty.py        # Penalty calculation
├─ config.yaml       # Configurable thresholds
└─ data_loader.py    # Load unemployment dataset
```

### 2. Create `risk/config.yaml`:
```yaml
version: "1.0"
thresholds:
  dropout_high: 0.3
  unemployment_high: 0.15
  cost_high: 50000

weights:
  market_saturation: 0.4
  skill_obsolescence: 0.3
  competition: 0.3
  dropout: 0.2
  unemployment: 0.2
  cost: 0.1

penalty:
  base_rate: 0.1
  scaling_factor: 1.5
```

### 3. Fix Formula:
```python
# In calculator.py
total_score = (
    simgr_scores["study"] * weights.study_score +
    simgr_scores["interest"] * weights.interest_score +
    simgr_scores["market"] * weights.market_score +
    simgr_scores["growth"] * weights.growth_score -
    simgr_scores["risk"] * weights.risk_score  # SUBTRACT (raw risk, not inverted)
)
```

---

## IX. SUMMARY

| Audit Item | Result |
|------------|--------|
| Dropout model | ❌ NOT IMPLEMENTED |
| Cost formula | ❌ NOT IMPLEMENTED |
| Unemployment dataset | ❌ NOT FOUND |
| Penalty formula | ⚠️ PARTIAL (indirect) |
| Threshold config | ❌ HARDCODED |
| risk/config.yaml | ❌ NOT FOUND |
| Formula compliance | ❌ VIOLATION (adds instead of subtracts) |

---

## X. FINAL VERDICT

### **❌ FAIL** - Risk Module does NOT meet DOC requirements.

**Critical Issues:**
1. No dropout model
2. No unemployment dataset
3. Penalty weights hardcoded
4. No config.yaml
5. Formula adds risk instead of subtracting

---

*Audit conducted with code-backed evidence only. No assumptions made.*
