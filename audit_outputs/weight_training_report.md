# Weight Training Pipeline Audit Report
## SIMGR + Stage 3 Full Governance Audit

**Date:** 2026-02-16  
**Auditor:** Principal System Architect  
**Status:** ❌ FAIL

---

## I. TRAINING PIPELINE VERIFICATION

### DOC Requirement:

```
training/train_weights.py
data/scoring/train.csv
features = [...]
target = final_score
models/weights/vX/weights.json
```

### Audit Results:

| Requirement | Evidence | Status |
|-------------|----------|--------|
| Training script | NOT FOUND | ❌ FAIL |
| Dataset path | NOT FOUND | ❌ FAIL |
| Feature columns | NOT DEFINED | ❌ FAIL |
| Target variable | NOT DEFINED | ❌ FAIL |
| Split logic | NOT IMPLEMENTED | ❌ FAIL |
| Validation method | NOT IMPLEMENTED | ❌ FAIL |
| Model export location | `models/weights/` NOT FOUND | ❌ FAIL |

---

## II. SEARCH EVIDENCE

### Files Searched:
- `**/train*.py` → Found: `trainer.py` (not weight learning), `train_eval.py` (evaluation)
- `**/weights/**` → NO FILES FOUND
- `weights.json` → NOT FOUND
- `LinearRegression|ElasticNet` → Found only in `shap_engine.py`, `feature_importance.py` (for XAI, not training)

### Existing Model Directory:
```
models/
├── active/
│   ├── .version
│   ├── classes.json
│   ├── fingerprint.json
│   ├── metrics.json    ← random_forest classifier (NOT regression)
│   └── model.pkl
└── v1/
```

**Note:** `models/active/metrics.json` contains:
```json
{
  "model_type": "random_forest",  ← NOT LinearRegression
  "accuracy": 0.9534,
  "f1": 0.9947
}
```

This is a **classification model**, NOT a weight regression model.

---

## III. CURRENT WEIGHT SOURCE

### File: `backend/scoring/config.py`

```python
@dataclass
class SIMGRWeights:
    study_score: float = 0.25      # ❌ HARDCODED
    interest_score: float = 0.25   # ❌ HARDCODED
    market_score: float = 0.25     # ❌ HARDCODED
    growth_score: float = 0.15     # ❌ HARDCODED
    risk_score: float = 0.10       # ❌ HARDCODED
```

**Verdict:** Weights are **HARDCODED**, not learned from data.

---

## IV. RUNTIME MAPPING AUDIT

### DOC Requirement:
```
wS, wI, wM, wG, wR
→ config
→ load point
→ injection into Engine
```

### Actual Implementation:

| Weight | Config Source | Load Point | Injection | Status |
|--------|---------------|------------|-----------|--------|
| wS | `SIMGRWeights.study_score` | Hardcode | `DEFAULT_CONFIG` | ❌ HARDCODE |
| wI | `SIMGRWeights.interest_score` | Hardcode | `DEFAULT_CONFIG` | ❌ HARDCODE |
| wM | `SIMGRWeights.market_score` | Hardcode | `DEFAULT_CONFIG` | ❌ HARDCODE |
| wG | `SIMGRWeights.growth_score` | Hardcode | `DEFAULT_CONFIG` | ❌ HARDCODE |
| wR | `SIMGRWeights.risk_score` | Hardcode | `DEFAULT_CONFIG` | ❌ HARDCODE |

**No dynamic loading from file/model detected.**

---

## V. MISSING COMPONENTS

### Required Pipeline:
```
1. Dataset loader           ❌ NOT IMPLEMENTED
2. StandardScaler           ❌ NOT IMPLEMENTED
3. LinearRegression/ElasticNet  ❌ NOT IMPLEMENTED
4. Constraint: sum(w)=1     ❌ NOT IMPLEMENTED (only validation)
5. Cross-validation         ❌ NOT IMPLEMENTED
6. Save weights             ❌ NOT IMPLEMENTED
```

### Required Output:
```
models/weights/vX/
 ├── weights.json        ❌ NOT FOUND
 ├── metrics.json (R2/MAE/RMSE)  ❌ NOT FOUND
 └── card.md             ❌ NOT FOUND
```

---

## VI. FIX PROPOSAL

### Create Weight Learning Pipeline:

```python
# training/train_weights.py (TO BE CREATED)

from sklearn.linear_model import ElasticNet
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
import json

# Load training data
df = pd.read_csv("data/scoring/train.csv")

# Features (S, I, M, G, R component scores)
features = ["study_score", "interest_score", "market_score", 
            "growth_score", "risk_score"]
X = df[features]
y = df["final_score"]  # Target

# Scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Train with constraint
model = ElasticNet(positive=True)  # Non-negative weights
model.fit(X_scaled, y)

# Normalize to sum=1
weights = model.coef_ / model.coef_.sum()

# Save
output = {
    "study_score": weights[0],
    "interest_score": weights[1],
    "market_score": weights[2],
    "growth_score": weights[3],
    "risk_score": weights[4],
    "version": "v1",
    "trained_at": datetime.now().isoformat(),
}

with open("models/weights/v1/weights.json", "w") as f:
    json.dump(output, f, indent=2)

# Save metrics
metrics = {
    "R2": cross_val_score(model, X_scaled, y, cv=5, scoring="r2").mean(),
    "MAE": -cross_val_score(model, X_scaled, y, cv=5, scoring="neg_mean_absolute_error").mean(),
    "RMSE": (-cross_val_score(model, X_scaled, y, cv=5, scoring="neg_mean_squared_error").mean())**0.5,
}
```

---

## VII. SUMMARY

| Requirement | Status |
|-------------|--------|
| Training script exists | ❌ FAIL |
| Dataset exists | ❌ FAIL |
| Regression model | ❌ FAIL |
| Weight versioning | ❌ FAIL |
| Model metrics | ❌ FAIL |
| Dynamic loading | ❌ FAIL |

---

## VIII. FINAL VERDICT

### **❌ FAIL** - Weight Learning Pipeline NOT IMPLEMENTED

**Weights are hardcoded in `config.py`**

**Required Actions:**
1. Create `training/train_weights.py`
2. Create training dataset `data/scoring/train.csv`
3. Implement regression with constraints
4. Save to `models/weights/vX/`
5. Implement dynamic loading in config

---

*Audit conducted with code-backed evidence only. No assumptions made.*
