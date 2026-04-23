# Coverage Map - GĐ6 Phase

## GĐ6: COVERAGE RECOVERY - Path to Branch Mapping

This document maps code paths to their test coverage status.

---

## Priority 1: calculator.py (96.4% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 25-45 | `__init__` - config validation | test_calculator.py::TestSIMGRCalculator | ✅ PASS |
| 50-70 | `_validate_components()` | test_calculator.py::TestSIMGRCalculator | ✅ PASS |
| 75-120 | `calculate()` main entry | test_calculator.py::TestCalculatorCalculate | ✅ PASS |
| 125-165 | `_compute_component()` | test_calculator.py::TestComponentComputation | ✅ PASS |
| 58 | `if config is None` edge | - | ⚠️ MISS |
| 176 | `raise TypeError` branch | - | ⚠️ MISS |

## Priority 2: engine.py (60.0% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 60-95 | `__init__` initialization | test_engine.py::TestRankingEngineInit | ✅ PASS |
| 100-165 | `rank()` main pipeline | test_engine.py::TestRankingEngineRank | ⚠️ PARTIAL |
| 173-181 | `_build_strategy()` builder | - | ⚠️ MISS |
| 286-345 | `score_jobs()` facade | - | ⚠️ MISS |
| 399-487 | Input/Output handling | - | ⚠️ MISS |

## Priority 3: components/risk.py (98.7% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 50-90 | `score()` main entry | test_risk.py::TestRiskScore | ✅ PASS |
| 95-150 | `_compute_*` sub-components | test_risk.py::TestRiskSubComponents | ✅ PASS |
| 158 | Exception handler | - | ⚠️ MISS |
| 200-250 | Dataset lookups | test_risk.py::TestLookupValue | ✅ PASS |
| 300-386 | Legacy fallback | test_risk.py::TestLegacyFallback | ✅ PASS |

## Priority 4: components/interest.py (97.3% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 30-70 | `score()` main entry | test_interest.py::TestInterestScore | ✅ PASS |
| 80-100 | `_normalize_set()` | test_interest.py::TestNormalizeSet | ⚠️ PARTIAL |
| 110-150 | `_compute_nlp_factor()` | test_interest.py::TestNLPFactor | ✅ PASS |
| 131, 137 | Edge cases | - | ⚠️ MISS |

## Priority 5: components/market.py (86.4% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 30-65 | `score()` main entry | test_market.py::TestMarketScore | ✅ PASS |
| 105 | Cache miss branch | - | ⚠️ MISS |
| 116 | Fallback value | - | ⚠️ MISS |
| 142-145 | Debug mode extras | - | ⚠️ MISS |

## Priority 6: scoring.py (90.4% Coverage)

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 40-80 | `__init__` | test_scoring.py::TestSIMGRScorerInit | ✅ PASS |
| 100-150 | `score()` entry point | test_scoring.py::TestScoreDirectComponents | ✅ PASS |
| 190-194 | Error handling | - | ⚠️ MISS |
| 340-341, 382 | Edge cases | - | ⚠️ MISS |

## Priority 7: strategies.py (100% Coverage) ✅

| Line Range | Branch/Path | Test File | Status |
|------------|-------------|-----------|--------|
| 30-55 | `ScoringStrategy.__init__` | test_strategies.py::TestScoringStrategyBase | ✅ PASS |
| 60-100 | `score_one()` | test_strategies.py::TestScoreOne | ✅ PASS |
| 145-200 | `rank()` | test_strategies.py::TestRank | ✅ PASS |
| 250-300 | `WeightedScoringStrategy` | test_strategies.py::TestWeightedScoringStrategy | ✅ PASS |
| 310-370 | `PersonalizedScoringStrategy` | test_strategies.py::TestPersonalizedScoringStrategy | ✅ PASS |
| 375-389 | `StrategyFactory` | test_strategies.py::TestStrategyFactory | ✅ PASS |

---

## Summary

| Module | Coverage | Target | Status |
|--------|----------|--------|--------|
| calculator.py | 96.4% | ≥90% | ✅ PASS |
| strategies.py | 100% | ≥85% | ✅ PASS |
| scoring.py | 90.4% | ≥85% | ✅ PASS |
| risk.py | 98.7% | ≥85% | ✅ PASS |
| interest.py | 97.3% | ≥85% | ✅ PASS |
| market.py | 86.4% | ≥85% | ✅ PASS |
| engine.py | 60.0% | ≥85% | ❌ FAIL |
| study.py | 92.2% | ≥85% | ✅ PASS |
| growth.py | 95.6% | ≥85% | ✅ PASS |

---

Generated: 2026-02-17
Phase: GĐ6 Coverage Recovery
