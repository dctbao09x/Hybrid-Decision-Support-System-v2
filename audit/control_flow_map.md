# Control Flow Map
**Auditor:** Independent AI Auditor  
**Date:** 2026-02-16  
**Method:** Code tracing

---

## 1. Primary Control Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           API LAYER                                      │
│  scoring_router.py::rank_careers()                                       │
│         │                                                                │
│         ▼                                                                │
│  [Auth] require_permission(Permission.SCORING_EXECUTE)                   │
│         │                                                                │
│         ▼                                                                │
│  [Controller] get_main_controller().dispatch(                            │
│                  service="scoring",                                      │
│                  action="rank",                                          │
│                  payload={...}                                           │
│               )                                                          │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        CONTROLLER LAYER                                  │
│  main_controller.py::dispatch()                                          │
│         │                                                                │
│         ▼                                                                │
│  _handle_scoring_rank() [line 367]                                       │
│         │                                                                │
│         ▼                                                                │
│  from backend.scoring.engine import RankingEngine                        │
│  from backend.scoring.config import DEFAULT_CONFIG                       │
│         │                                                                │
│         ▼                                                                │
│  engine = RankingEngine(default_config=DEFAULT_CONFIG)                   │
│  engine.rank(user, careers, strategy_name)                               │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         ENGINE LAYER                                     │
│  engine.py::RankingEngine.rank()                                         │
│         │                                                                │
│         ▼                                                                │
│  strategy = StrategyFactory.create(strategy_name, config)                │
│         │                                                                │
│         ▼                                                                │
│  results = strategy.rank(user, careers)                                  │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        STRATEGY LAYER                                    │
│  strategies.py::ScoringStrategy.rank()                                   │
│         │                                                                │
│         ▼                                                                │
│  for career in careers:                                                  │
│      scored_career = self.score_one(user, career)                        │
│         │                                                                │
│         ▼                                                                │
│  total, breakdown = self._calculator.calculate(user, career)             │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       CALCULATOR LAYER                                   │
│  calculator.py::SIMGRCalculator.calculate()                              │
│         │                                                                │
│         ▼                                                                │
│  for component_name in ["study", "interest", "market", "growth", "risk"]:│
│      result = self._compute_component(component_name, user, career)      │
│         │                                                                │
│         ▼                                                                │
│  component_fn = self.config.component_map.get(component_name)            │
│  result = component_fn(career, user, self.config)                        │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       COMPONENT LAYER                                    │
│  components/{study,interest,market,growth,risk}.py::score()              │
│         │                                                                │
│         ▼                                                                │
│  Compute sub-factors                                                     │
│  Apply component formula                                                 │
│  Return ScoreResult(value, meta)                                         │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       NORMALIZER LAYER                                   │
│  normalizer.py::DataNormalizer.clamp()                                   │
│         │                                                                │
│         ▼                                                                │
│  Ensure score ∈ [0, 1]                                                   │
│  Handle None, NaN, Inf                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Alternate Entry Points Detected

### 2.1 Direct SIMGRScorer (Bypass Path)
```
SIMGRScorer.score(input_dict)
    │
    ▼
_score_direct_components() OR _score_full_pipeline()
    │
    ▼
RankingEngine.rank() [same as above]
```

**Risk:** Bypasses API authentication if imported directly.

### 2.2 Warmup Module (Internal Path)
```
backend/ops/warmup.py::_warmup_scoring()
    │
    ▼
from backend.scoring.scoring import SIMGRScorer
from backend.scoring.engine import RankingEngine
    │
    ▼
SIMGRScorer(config=DEFAULT_CONFIG)
RankingEngine(default_config=DEFAULT_CONFIG)
```

**Risk:** Internal use only, but shows direct access is intentional for warmup.

---

## 3. Skip Path Analysis

| Layer | Has Skip? | Evidence |
|-------|-----------|----------|
| API → Controller | ❌ No | All routes use controller.dispatch() |
| Controller → Engine | ❌ No | _handle_scoring_rank always creates engine |
| Engine → Strategy | ❌ No | Always calls strategy.rank() |
| Strategy → Calculator | ❌ No | Always calls _calculator.calculate() |
| Calculator → Components | ❌ No | Iterates all 5 components |
| Components → Normalizer | ❌ No | All return clamped values |

**Finding:** No skip paths in main flow.

---

## 4. Parallel Scoring Detection

### Check: Are multiple engines instantiated?
```python
# main_controller.py:374
engine = RankingEngine(default_config=DEFAULT_CONFIG)
```

**Finding:** Engine is instantiated per-request, not shared. No parallel scoring.

---

## 5. Legacy Path Detection

### Check: api_legacy.py
```python
# backend/api_legacy.py exists
# Contains routes: /analyze, /recommend
```

**Finding:** Legacy paths exist but do not include scoring endpoints.

### Check: scoring_router_backup.py
```
backend/api/routers/scoring_router_backup.py exists
```

**Finding:** Backup router exists. May contain outdated code.

---

## 6. Field Mismatches

| API Field | Controller Field | Engine Field | Status |
|-----------|-----------------|--------------|--------|
| user_profile | user_profile | user | ✅ Mapped |
| careers | careers | careers | ✅ Mapped |
| strategy | strategy | strategy_name | ✅ Mapped |
| top_n | top_n | - | ⚠️ Sliced post-rank |

### Breakdown Field Mismatch
```python
# API expects:
breakdown = {
    "study_score": ...,
    "interest_score": ...,
    "skill_score": ...,       # <-- MISMATCH: should be market_score
    "market_score": ...,
    "confidence_score": ...   # <-- MISMATCH: not in calculator
}

# Calculator produces:
breakdown = {
    "study_score": ...,
    "interest_score": ...,
    "market_score": ...,
    "growth_score": ...,      # <-- Not in API expectation
    "risk_score": ...         # <-- Not in API expectation
}
```

**Finding:** Field mismatch between API expectation and calculator output.

---

## 7. Shadow Variables

### Check: Controller local imports
```python
# main_controller.py:370-372
from backend.scoring.engine import RankingEngine
from backend.scoring.models import UserProfile, CareerData
from backend.scoring.config import DEFAULT_CONFIG
```

**Finding:** Imports are local (inside method), not module-level. Good practice.

### Check: No global mutable state
- `DEFAULT_CONFIG` is loaded once at module import
- Engine is created per-request
- No global cache in scoring path

---

## 8. Control Flow Verdict

| Check | Status | Notes |
|-------|--------|-------|
| No skip paths | ✅ PASS | All layers traversed |
| No parallel scoring | ✅ PASS | Single engine per request |
| No legacy scoring path | ✅ PASS | Legacy API doesn't include scoring |
| Field consistency | ❌ FAIL | breakdown fields mismatch |
| No shadow variables | ✅ PASS | Local imports, no global mutables |

**CONTROL FLOW: CONDITIONAL PASS**

Main flow is correct. Field mismatch between API and calculator needs fixing.
