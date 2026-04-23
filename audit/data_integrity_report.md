# Data Pipeline Integrity Report
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** Code tracing and runtime inspection

---

## 1. Data Sources Inventory

### 1.1 Market Data
| Field | Source | Parser | Validator |
|-------|--------|--------|-----------|
| ai_relevance | MarketCacheLoader OR CareerData | float() | normalizer.clamp() |
| growth_rate | MarketCacheLoader OR CareerData | float() | normalizer.clamp() |
| competition | MarketCacheLoader OR CareerData | float() | normalizer.clamp() |
| salary_score | HARDCODED SALARY_DATASET | dict lookup | fuzzy match |

**Cache Location:** `backend/market/cache_loader.py`
**Fallback:** Career input fields

### 1.2 Growth Data
| Field | Source | Parser | Validator |
|-------|--------|--------|-----------|
| demand_growth | DEMAND_FORECAST dict + job.growth_rate | dict lookup | blend calculation |
| salary_growth | SALARY_GROWTH_DATA dict + job.ai_relevance | dict lookup | 0.7*base + 0.3*ai |
| lifecycle | LIFECYCLE_DATASET dict | dict lookup | fallback 0.50 |

**Data Location:** Hardcoded in `backend/scoring/components/growth.py`
**External Data:** None loaded at runtime

### 1.3 Risk Data
| Field | Source | Parser | Validator |
|-------|--------|--------|-----------|
| saturation | job.competition | direct | clamp [0,1] |
| obsolescence | job.growth_rate, job.ai_relevance | computation | clamp |
| dropout | DROPOUT_RISK_DATASET | dict lookup | fallback 0.35 |
| unemployment | UNEMPLOYMENT_RISK_DATASET | dict lookup | fallback 0.30 |
| cost | COST_RISK_DATASET | dict lookup | fallback 0.40 |

**External Files Checked:**
- `data/risk/unemployment/rates.csv` - **NOT FOUND**
- Cost dataset - **PARSING FAILED**

---

## 2. Training Data

### Location
`backend/data/scoring/train.csv`

### Schema
```csv
study,interest,market,growth,risk,outcome,weight
```

### Statistics
- **Records:** 50
- **Columns:** 7 (5 components + outcome + weight)
- **Outcome range:** [0.32, 0.95]
- **All values:** [0, 1] range verified

### Validation
```python
# From train_weights.py:load_data()
for col in COMPONENTS + ["outcome"]:
    if df[col].min() < 0 or df[col].max() > 1:
        logger.warning(f"Column {col} has values outside [0,1]. Clamping.")
        df[col] = df[col].clip(0, 1)
```

---

## 3. Silent Failures Detected

### 3.1 Missing Unemployment Dataset
```
Runtime Log: "Unemployment dataset not found: data/risk/unemployment/rates.csv"
```
**Behavior:** Silent fallback to UNEMPLOYMENT_RISK_DATASET dict
**Impact:** Uses hardcoded fallback values without user notification

### 3.2 Cost Dataset Parse Error
```
Runtime Log: "Failed to load cost dataset: could not convert string to float: 'variable'"
```
**Behavior:** Silent fallback to COST_RISK_DATASET dict
**Impact:** Uses hardcoded fallback values without user notification

### 3.3 Market Cache Miss
```
Runtime Log: "Market cache miss for career=%s, using career input fields"
```
**Behavior:** Falls back to career input fields
**Impact:** Less accurate market data, but logged

---

## 4. Default Masking

| Component | Default Mask | Evidence |
|-----------|--------------|----------|
| study | 0.5 (neutral) | calculator.py:96 |
| interest | 0.5 (neutral) | calculator.py:96 |
| market | 0.5 (neutral) | calculator.py:96 |
| growth | 0.5 (neutral) | calculator.py:96 |
| risk | 0.0 (safe) | calculator.py:108 |

**Finding:** Failed components default to 0.5, masking the failure from final score.

---

## 5. Versioning

### Weights Versioning
- **Path:** `models/weights/{version}/weights.json`
- **Active:** `models/weights/active/weights.json` (symlink)
- **Current Version:** v1
- **Metadata present:** version, created_at, metrics

### Dataset Versioning
**NOT IMPLEMENTED**
- No version tracking for training data
- No version tracking for hardcoded datasets
- No schema version in training CSV

---

## 6. Cache Integrity

### Market Cache
- **Loader:** `MarketCacheLoader.lookup_by_title()`
- **TTL:** Not enforced at runtime
- **Validation:** Basic type casting to float

### Growth Cache (Data Freshness Module)
- **Module:** `backend/scoring/components/growth_refresh.py`
- **TTL:** 90 days
- **Checksum:** SHA256 on data
- **Status:** Code exists, but not wired to main scoring path

---

## 7. Data Pipeline Integrity Summary

| Check | Status | Evidence |
|-------|--------|----------|
| Input validation | ✅ PASS | Pydantic models |
| Parser safety | ✅ PASS | try/except around loads |
| Cleaner | ⚠️ PARTIAL | Clamp only, no outlier removal |
| Validator | ⚠️ PARTIAL | Range check only |
| Cache | ✅ PASS | MarketCacheLoader exists |
| Versioning | ❌ FAIL | Only weights versioned |
| Silent failures | ❌ FAIL | Multiple silent fallbacks |
| Default masking | ❌ FAIL | 0.5 masks failures |

---

## 8. Verdict

**DATA PIPELINE INTEGRITY: CONDITIONAL PASS**

**Passes:**
- Input validation via Pydantic
- Output clamping via normalizer
- Weights have versioning

**Fails:**
- Silent fallback to hardcoded datasets
- Missing external datasets (unemployment, cost)
- Dataset versioning not implemented
- Component failure masked by 0.5 default

**Recommendations:**
1. Implement dataset versioning
2. Surface data quality warnings to API response
3. Add freshness metadata to score breakdown
4. Fail loudly when external data missing
