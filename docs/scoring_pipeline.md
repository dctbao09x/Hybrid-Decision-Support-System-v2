# Scoring Pipeline Documentation

## Overview

The scoring engine implements the SIMGR (Study, Interest, Market, Growth, Risk) standard for career recommendation scoring. This document outlines the pipeline architecture, components, and usage.

## Architecture

### Pipeline Flow

```
Prompt3 Output → Feature Vector → Scoring → Ranking
```

1. **Prompt3 Processing**: User analysis output is normalized into UserProfile
2. **Feature Vector**: Career data is structured into CareerData objects
3. **Component Scoring**: Each SIMGR component computes scores [0,1]
4. **Aggregation**: Weighted combination produces final scores
5. **Ranking**: Careers sorted by total score

### Core Components

#### SIMGR Components

- **Study**: Skill match and education fit
- **Interest**: Interest alignment via Jaccard similarity
- **Market**: Market attractiveness (AI relevance + growth - competition)
- **Growth**: Career growth potential
- **Risk**: Risk assessment (inverted, 1.0 = low risk)

#### Key Classes

- `UserProfile`: Normalized user data
- `CareerData`: Structured career information
- `ScoreResult`: Component score with metadata
- `ScoringResult`: Complete job scoring result
- `ScoringConfig`: Configuration with weights and settings

## API Reference

### Primary Interface

```python
from backend.scoring import score_jobs

def score_jobs(
    clean_jobs: List[CareerData],
    user_profile: UserProfile
) -> List[ScoringResult]:
    """Score jobs for user, return detailed results with contributions."""
```

### Legacy Interface

```python
from backend.scoring import rank_careers

def rank_careers(
    user: UserProfile,
    careers: List[CareerData],
    *,
    config: Optional[ScoringConfig] = None,
    strategy: Optional[str] = None,
) -> List[ScoredCareer]:
    """Legacy ranking interface, returns sorted ScoredCareer list."""
```

### Configuration

```python
from backend.scoring import ScoringConfig

# Create custom config
config = ScoringConfig.create_custom(
    study=0.3, interest=0.3, market=0.2, growth=0.1, risk=0.1
)

# Hot reload
config.reload()
```

## Component Specifications

### Component Interface

Each component implements:

```python
def score(job: CareerData, user: UserProfile, config: ScoringConfig) -> ScoreResult:
    """Pure function returning ScoreResult with value [0,1] and meta dict."""
```

### Deterministic & Pure

- No side effects
- Deterministic output for same inputs
- No external dependencies
- Thread-safe

### Type Hints & Validation

- Full type annotations
- Pydantic validation
- Strict input validation
- Safe error handling

## Prompt3 Integration

### Normalizer

```python
from backend.scoring.normalizer import Prompt3Normalizer

user_profile = Prompt3Normalizer.normalize_user_profile_from_analyze(analyze_output)
```

### Schema Mapping

Prompt3 fields mapped to UserProfile:
- `skill_tags` → `skills`
- `interest_tags` → `interests`
- `education_level` → `education_level`
- `confidence_score` → `ability_score`, `confidence_score`

## Explainability

### Contributions Mapping

Each ScoringResult includes:

```python
{
    "contributions": {
        "study": {"weight": 0.25, "contribution": 0.2125},
        "interest": {"weight": 0.25, "contribution": 0.20},
        # ...
    }
}
```

### Tracing

```python
from backend.scoring.explain import ScoringTracer

tracer = ScoringTracer(enabled=True)
# Traces component computations with metadata
```

## Configuration Management

### Weights

SIMGR weights must sum to 1.0:
- study_score: 0.25
- interest_score: 0.25
- market_score: 0.25
- growth_score: 0.15
- risk_score: 0.10

### Hot Reload

```python
config.reload()  # Reinitialize component map
```

### No Magic Numbers

All constants defined in config classes:
- Component weights
- Thresholds
- Default values

## Testing & Quality

### Test Coverage

- Component unit tests
- Integration tests
- Regression tests against baseline
- Coverage ≥ 90%

### Baseline Validation

Results validated against baseline within ±2% deviation.

### Compatibility

- Old API (`rank_careers`) remains functional
- New API (`score_jobs`) provides enhanced features
- Backward compatible schemas

## Error Handling

### Fail-Safe Design

- Invalid inputs return default scores (0.5)
- Component failures don't break pipeline
- Logging for debugging
- Graceful degradation

### Validation

- Input validation at boundaries
- Type checking
- Range validation for scores [0,1]

## Performance

### Optimizations

- Pure functions enable caching
- Lazy component loading
- Minimal object creation
- Efficient similarity computations

### Determinism

- No randomness
- Consistent ordering
- Reproducible results

## Migration Guide

### From Legacy API

```python
# Old
ranked = rank_careers(user, careers)

# New (enhanced)
scored = score_jobs(careers, user)
# Access contributions, detailed breakdowns
```

### Configuration Updates

```python
# Old hardcoded weights
# New config-driven
config = ScoringConfig.create_custom(study=0.3, ...)
```

## Quality Gates

- ✅ Old API not broken
- ✅ Results ±2% baseline
- ✅ Reproducible
- ✅ No duplicate logic
- ✅ Type safety
- ✅ Test coverage ≥90%
- ✅ Documentation complete
