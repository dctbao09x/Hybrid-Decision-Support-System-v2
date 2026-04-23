# Data Quality Enhancement Design
## Response Consistency Validation & Adaptive Questioning

**Version:** 1.0  
**Date:** 2026-02-21  
**Status:** DESIGN APPROVED

---

## System Rules (IMMUTABLE)

| Rule | Description |
|------|-------------|
| SIMGRScorer FROZEN | No modifications to `backend/scoring/scoring.py` |
| Base Score Isolation | Confidence score CANNOT influence base score calculation |
| Confidence Scope | Affects ONLY: explanation quality, flagging, audit trail |

---

## I. Validation Architecture

### 1.1 Component Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      ConsistencyValidationLayer                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    INPUT (Raw Survey Responses)                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                  │                                      │
│                                  ▼                                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    ConsistencyValidator                           │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │  │
│  │  │   Speed     │ │   Trait     │ │   Likert    │ │   Random    │ │  │
│  │  │  Anomaly    │ │Contradiction│ │ Uniformity  │ │  Pattern    │ │  │
│  │  │  Detector   │ │   Matrix    │ │  Detector   │ │  Entropy    │ │  │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ │  │
│  │         └───────────────┴───────────────┴───────────────┘        │  │
│  │                                 │                                 │  │
│  │                                 ▼                                 │  │
│  │                   ConfidenceScoreAggregator                       │  │
│  │                     confidence ∈ [0.0, 1.0]                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                  │                                      │
│              ┌───────────────────┼───────────────────┐                 │
│              ▼                   ▼                   ▼                  │
│    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐       │
│    │ FLAGGING ONLY   │  │ EXPLANATION     │  │ ADAPTIVE        │       │
│    │ (quality_flag)  │  │ DEGRADATION     │  │ QUESTIONING     │       │
│    └─────────────────┘  └─────────────────┘  └─────────────────┘       │
│                                                                         │
│  ════════════════════════════════════════════════════════════════════  │
│  ║  SCORING BOUNDARY (IMPENETRABLE)                                 ║  │
│  ════════════════════════════════════════════════════════════════════  │
│                                  │                                      │
│                                  ▼                                      │
│             ┌──────────────────────────────────────────┐               │
│             │          SIMGRScorer (UNTOUCHED)         │               │
│             │    confidence_score IGNORED in formula   │               │
│             └──────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Detector Specifications

#### A. Speed Anomaly Detector

**Purpose:** Identify suspiciously fast or slow responses indicating careless completion.

```python
class SpeedAnomalyDetector:
    """
    Detects response timing anomalies.
    
    Thresholds (per-question):
        - MIN_RESPONSE_MS: 800ms (humanly impossible below)
        - MAX_RESPONSE_MS: 120000ms (2 minutes - disengagement)
        - EXPECTED_MEDIAN_MS: 3000-8000ms (normal range)
    
    Metrics:
        - questions_too_fast: count of responses < MIN_RESPONSE_MS
        - questions_too_slow: count of responses > MAX_RESPONSE_MS
        - median_deviation: |median - expected_median| / expected_median
    """
    
    CONFIG = {
        "min_response_ms": 800,
        "max_response_ms": 120000,
        "expected_median_range": (3000, 8000),
        "fast_ratio_threshold": 0.3,   # >30% fast = anomaly
        "slow_ratio_threshold": 0.4,   # >40% slow = anomaly
    }
    
    def calculate_penalty(self, response_times: List[int]) -> float:
        """
        Returns penalty ∈ [0, 1] where 1 = maximum anomaly.
        
        Formula:
            fast_ratio = questions_too_fast / total_questions
            slow_ratio = questions_too_slow / total_questions
            
            speed_penalty = (
                0.4 * min(fast_ratio / fast_ratio_threshold, 1.0) +
                0.3 * min(slow_ratio / slow_ratio_threshold, 1.0) +
                0.3 * median_deviation_penalty
            )
        """
```

#### B. Trait Contradiction Matrix

**Purpose:** Detect logically inconsistent responses across related questions.

```python
class TraitContradictionMatrix:
    """
    Detects contradictions in personality/interest responses.
    
    Contradiction pairs (examples):
        - "I enjoy working alone" vs "I prefer team collaboration"
        - "I like detailed planning" vs "I prefer spontaneous decisions"
        - "Math is my strongest subject" vs "I avoid quantitative tasks"
    
    Scoring:
        - Each contradiction pair has weight ∈ [0.5, 1.0]
        - Contradiction detected if |response_a - opposite(response_b)| < 2
          (on 7-point Likert scale)
    """
    
    CONTRADICTION_PAIRS = [
        # (question_id_a, question_id_b, weight, is_inverse)
        ("work_alone_pref", "team_collab_pref", 0.9, True),
        ("detail_planning", "spontaneous_decision", 0.8, True),
        ("math_strength", "avoid_quantitative", 1.0, True),
        ("creative_expression", "structured_tasks_pref", 0.7, True),
        ("tech_interest", "tech_avoidance", 1.0, True),
        ("leadership_desire", "follower_preference", 0.85, True),
        ("risk_tolerance", "security_priority", 0.75, True),
        ("analytical_thinking", "intuitive_decision", 0.6, True),
    ]
    
    def calculate_penalty(self, responses: Dict[str, int]) -> float:
        """
        Returns penalty ∈ [0, 1] where 1 = maximum contradiction.
        
        Formula:
            contradiction_score = Σ(weight_i * is_contradicted_i) / Σ(weight_i)
        """
```

#### C. Likert Uniformity Detector

**Purpose:** Detect straight-lining (all same response) or patterned responses.

```python
class LikertUniformityDetector:
    """
    Detects uniform or patterned Likert scale responses.
    
    Patterns detected:
        - Straight-line: all responses same value (e.g., all 4s)
        - Alternating: 1,7,1,7,1,7 or 3,5,3,5,3,5
        - Sequential: 1,2,3,4,5,6,7,1,2,3...
        - Edge-only: only 1s and 7s used
    
    Metrics:
        - unique_values_ratio: unique_count / total_questions
        - mode_frequency: max_count / total_questions
        - pattern_correlation: correlation with known bad patterns
    """
    
    CONFIG = {
        "min_unique_ratio": 0.3,      # Must use at least 30% of scale
        "max_mode_frequency": 0.5,    # No single value > 50%
        "edge_only_threshold": 0.8,   # >80% at edges = anomaly
    }
    
    KNOWN_PATTERNS = [
        [1, 7, 1, 7, 1, 7, 1, 7],     # Alternating extremes
        [4, 4, 4, 4, 4, 4, 4, 4],     # Middle-only
        [1, 2, 3, 4, 5, 6, 7, 1],     # Sequential
        [7, 6, 5, 4, 3, 2, 1, 7],     # Reverse sequential
    ]
    
    def calculate_penalty(self, responses: List[int]) -> float:
        """
        Returns penalty ∈ [0, 1] where 1 = maximum uniformity.
        
        Formula:
            uniformity_penalty = (
                0.35 * (1 - unique_values_ratio / expected_ratio) +
                0.35 * max(0, mode_frequency - max_mode_frequency) * 2 +
                0.30 * max_pattern_correlation
            )
        """
```

#### D. Random Pattern Entropy Analyzer

**Purpose:** Detect responses that are too random (low engagement) or too structured (gaming).

```python
class RandomPatternEntropyAnalyzer:
    """
    Analyzes response entropy to detect disengaged or gaming behavior.
    
    Theory:
        - Genuine responses: moderate entropy (structured but varied)
        - Random clicking: high entropy (no structure)
        - Gaming/straight-lining: low entropy (too predictable)
    
    Expected entropy (7-point Likert, n questions):
        - entropy_min_expected: 1.5 bits (some structure)
        - entropy_max_expected: 2.5 bits (reasonable variation)
        - entropy_random: ~2.81 bits (log2(7))
    """
    
    CONFIG = {
        "entropy_min_expected": 1.5,
        "entropy_max_expected": 2.5,
        "entropy_random": 2.807,       # log2(7)
    }
    
    def calculate_penalty(self, responses: List[int]) -> float:
        """
        Returns penalty ∈ [0, 1] where 1 = maximum entropy anomaly.
        
        Formula:
            H = -Σ(p_i * log2(p_i))  # Shannon entropy
            
            if H < entropy_min_expected:
                penalty = (entropy_min_expected - H) / entropy_min_expected
            elif H > entropy_max_expected:
                penalty = (H - entropy_max_expected) / (entropy_random - entropy_max_expected)
            else:
                penalty = 0
        """
```

---

## II. Confidence Score Formula

### 2.1 Aggregation Formula

```python
def compute_confidence_score(
    speed_penalty: float,
    contradiction_penalty: float,
    uniformity_penalty: float,
    entropy_penalty: float,
    weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Compute aggregate confidence score.
    
    CRITICAL: This score does NOT affect base scoring.
    
    Args:
        speed_penalty: ∈ [0, 1] from SpeedAnomalyDetector
        contradiction_penalty: ∈ [0, 1] from TraitContradictionMatrix
        uniformity_penalty: ∈ [0, 1] from LikertUniformityDetector  
        entropy_penalty: ∈ [0, 1] from RandomPatternEntropyAnalyzer
        weights: Optional custom weights (must sum to 1.0)
    
    Returns:
        confidence_score ∈ [0.0, 1.0] where:
            1.0 = highest confidence (no anomalies)
            0.0 = lowest confidence (maximum anomalies)
    
    Default weights:
        speed: 0.25
        contradiction: 0.30
        uniformity: 0.25
        entropy: 0.20
    """
    DEFAULT_WEIGHTS = {
        "speed": 0.25,
        "contradiction": 0.30,
        "uniformity": 0.25,
        "entropy": 0.20,
    }
    
    w = weights or DEFAULT_WEIGHTS
    
    # Weighted penalty sum
    total_penalty = (
        w["speed"] * speed_penalty +
        w["contradiction"] * contradiction_penalty +
        w["uniformity"] * uniformity_penalty +
        w["entropy"] * entropy_penalty
    )
    
    # Confidence = 1 - penalty (clamped)
    confidence = max(0.0, min(1.0, 1.0 - total_penalty))
    
    return round(confidence, 4)
```

### 2.2 Confidence Bands

| Band | Range | Interpretation | Action |
|------|-------|----------------|--------|
| HIGH | [0.8, 1.0] | Reliable responses | Full explanation |
| MEDIUM | [0.6, 0.8) | Minor anomalies | Warning flag, full explanation |
| LOW | [0.4, 0.6) | Significant anomalies | Degraded explanation, adaptive questions |
| CRITICAL | [0.0, 0.4) | Likely invalid | Minimal explanation, force re-survey option |

---

## III. Adaptive Branch Logic

### 3.1 Threshold Policy

```python
@dataclass(frozen=True)
class ConfidenceThresholdPolicy:
    """
    Immutable threshold policy for confidence-based actions.
    
    CRITICAL: These thresholds NEVER affect base scoring.
    """
    
    # Explanation degradation
    EXPLANATION_FULL_THRESHOLD: float = 0.6
    EXPLANATION_MINIMAL_THRESHOLD: float = 0.3
    
    # Flagging
    FLAG_WARNING_THRESHOLD: float = 0.7
    FLAG_CRITICAL_THRESHOLD: float = 0.4
    
    # Adaptive questioning trigger
    ADAPTIVE_TRIGGER_THRESHOLD: float = 0.6
    
    # Hard stop (offer re-survey)
    RESURVEY_OFFER_THRESHOLD: float = 0.3
    
    def get_explanation_mode(self, confidence: float) -> str:
        """
        Determine explanation mode based on confidence.
        
        Returns:
            "full" | "degraded" | "minimal"
        """
        if confidence >= self.EXPLANATION_FULL_THRESHOLD:
            return "full"
        elif confidence >= self.EXPLANATION_MINIMAL_THRESHOLD:
            return "degraded"
        else:
            return "minimal"
    
    def get_quality_flags(self, confidence: float) -> List[str]:
        """
        Return applicable quality flags.
        
        Flags DO NOT affect scoring, only metadata/UI.
        """
        flags = []
        if confidence < self.FLAG_CRITICAL_THRESHOLD:
            flags.append("CRITICAL_DATA_QUALITY")
        elif confidence < self.FLAG_WARNING_THRESHOLD:
            flags.append("WARNING_DATA_QUALITY")
        return flags
    
    def should_trigger_adaptive(self, confidence: float) -> bool:
        """Check if adaptive questioning should be triggered."""
        return confidence < self.ADAPTIVE_TRIGGER_THRESHOLD
    
    def should_offer_resurvey(self, confidence: float) -> bool:
        """Check if re-survey option should be offered."""
        return confidence < self.RESURVEY_OFFER_THRESHOLD
```

### 3.2 Explanation Degradation Logic

```python
class ExplanationDegradationStrategy:
    """
    Strategy for degrading explanation based on confidence.
    
    PRINCIPLE: Low confidence = less specific explanations.
    This prevents fabricated specificity when data is unreliable.
    """
    
    DEGRADATION_RULES = {
        "full": {
            "include_score_breakdown": True,
            "include_feature_impacts": True,
            "include_specific_recommendations": True,
            "include_career_comparisons": True,
            "llm_temperature": 0.3,      # More deterministic
        },
        "degraded": {
            "include_score_breakdown": True,
            "include_feature_impacts": False,  # Too unreliable
            "include_specific_recommendations": False,
            "include_career_comparisons": True,
            "llm_temperature": 0.5,
            "append_disclaimer": (
                "Note: Some response patterns suggest uncertainty in your answers. "
                "Consider retaking the assessment for more detailed guidance."
            ),
        },
        "minimal": {
            "include_score_breakdown": False,
            "include_feature_impacts": False,
            "include_specific_recommendations": False,
            "include_career_comparisons": False,
            "llm_temperature": 0.7,      # Generic is fine
            "append_disclaimer": (
                "Warning: Response quality is low. Results are tentative. "
                "We strongly recommend retaking the assessment carefully."
            ),
        },
    }
    
    def apply(self, base_explanation: Dict, confidence: float, policy: ConfidenceThresholdPolicy) -> Dict:
        """
        Apply degradation to explanation based on confidence.
        
        DOES NOT MODIFY SCORES. Only explanation content.
        """
        mode = policy.get_explanation_mode(confidence)
        rules = self.DEGRADATION_RULES[mode]
        
        degraded = base_explanation.copy()
        
        if not rules["include_score_breakdown"]:
            degraded.pop("score_breakdown", None)
        
        if not rules["include_feature_impacts"]:
            degraded.pop("feature_impacts", None)
            
        if not rules["include_specific_recommendations"]:
            degraded.pop("specific_recommendations", None)
            
        if not rules["include_career_comparisons"]:
            degraded.pop("career_comparisons", None)
        
        if "append_disclaimer" in rules:
            degraded["disclaimer"] = rules["append_disclaimer"]
        
        degraded["_meta"] = {
            "explanation_mode": mode,
            "confidence_score": confidence,
            "degradation_applied": mode != "full",
        }
        
        return degraded
```

---

## IV. Micro-Adaptive Question Injection

### 4.1 Injection Logic

```python
@dataclass
class AdaptiveQuestionConfig:
    """
    Configuration for adaptive question injection.
    
    CONSTRAINTS:
        - max_additional_questions: 5 (hard limit)
        - Cannot change base scoring formula
        - Questions only for confidence improvement
    """
    
    max_additional_questions: int = 5
    min_confidence_for_skip: float = 0.8
    question_selection_strategy: str = "targeted"  # "targeted" | "random"
    
    # Per-detector question limits
    speed_questions_max: int = 2
    contradiction_questions_max: int = 2
    uniformity_questions_max: int = 1


class AdaptiveQuestionInjector:
    """
    Injects follow-up questions to improve data quality.
    
    CRITICAL CONSTRAINTS:
        1. Questions DO NOT affect base scoring
        2. Only used to compute revised confidence
        3. Maximum 5 additional questions
        4. User can skip (results in no confidence improvement)
    """
    
    QUESTION_BANK = {
        "speed_verification": [
            {
                "id": "speed_v1",
                "text": "You answered some questions very quickly. Please reconsider: How confident are you in your career preferences?",
                "type": "likert_7",
                "targets": ["confidence_verification"],
            },
            {
                "id": "speed_v2", 
                "text": "Take a moment to reflect: Which statement best describes your work style?",
                "type": "multiple_choice",
                "options": ["Independent focused work", "Collaborative teamwork", "Mix of both", "No preference"],
                "targets": ["work_style_verification"],
            },
        ],
        "contradiction_resolution": [
            {
                "id": "contra_r1",
                "text": "Your responses show some variation. Please clarify: Do you prefer working alone or with others?",
                "type": "likert_7",
                "anchors": ["Strongly prefer alone", "Strongly prefer with others"],
                "targets": ["work_alone_pref", "team_collab_pref"],
            },
            {
                "id": "contra_r2",
                "text": "Please clarify: How do you prefer to make decisions?",
                "type": "multiple_choice",
                "options": ["Careful analysis and planning", "Quick intuition", "Depends on situation"],
                "targets": ["detail_planning", "spontaneous_decision"],
            },
        ],
        "uniformity_check": [
            {
                "id": "uniform_c1",
                "text": "Your responses suggest similar feelings about many topics. Is there any area where you feel particularly strong or weak?",
                "type": "open_text",
                "max_length": 200,
                "targets": ["uniformity_verification"],
            },
        ],
    }
    
    def select_questions(
        self,
        confidence_breakdown: Dict[str, float],
        config: AdaptiveQuestionConfig
    ) -> List[Dict]:
        """
        Select adaptive questions based on confidence breakdown.
        
        Selection priority (highest penalty first):
            1. Contradiction resolution (if contradiction_penalty > 0.3)
            2. Speed verification (if speed_penalty > 0.4)
            3. Uniformity check (if uniformity_penalty > 0.5)
        
        Returns:
            List of question dicts, max length = config.max_additional_questions
        """
        selected = []
        
        # Sort detectors by penalty (highest first)
        penalties = [
            ("contradiction", confidence_breakdown.get("contradiction_penalty", 0)),
            ("speed", confidence_breakdown.get("speed_penalty", 0)),
            ("uniformity", confidence_breakdown.get("uniformity_penalty", 0)),
        ]
        penalties.sort(key=lambda x: x[1], reverse=True)
        
        for detector, penalty in penalties:
            if len(selected) >= config.max_additional_questions:
                break
            
            if detector == "contradiction" and penalty > 0.3:
                questions = self.QUESTION_BANK["contradiction_resolution"]
                available = min(config.contradiction_questions_max, len(questions))
                selected.extend(questions[:available])
                
            elif detector == "speed" and penalty > 0.4:
                questions = self.QUESTION_BANK["speed_verification"]
                available = min(config.speed_questions_max, len(questions))
                selected.extend(questions[:available])
                
            elif detector == "uniformity" and penalty > 0.5:
                questions = self.QUESTION_BANK["uniformity_check"]
                available = min(config.uniformity_questions_max, len(questions))
                selected.extend(questions[:available])
        
        return selected[:config.max_additional_questions]
    
    def compute_confidence_adjustment(
        self,
        adaptive_responses: List[Dict],
        original_confidence: float
    ) -> float:
        """
        Compute confidence adjustment from adaptive responses.
        
        RULES:
            - Consistent responses: +0.1 to confidence (max)
            - Contradictory responses: no change (keep original)
            - Skipped: no change
        
        CRITICAL: Only affects confidence, NOT base scores.
        """
        if not adaptive_responses:
            return original_confidence
        
        valid_responses = [r for r in adaptive_responses if r.get("answered", False)]
        
        if not valid_responses:
            return original_confidence
        
        # Calculate consistency bonus
        consistency_score = self._evaluate_consistency(valid_responses)
        
        # Max bonus: 0.15 (can improve from 0.55 to 0.70)
        adjustment = min(0.15, consistency_score * 0.15)
        
        return min(1.0, original_confidence + adjustment)
```

### 4.2 Trigger Conditions

```python
class AdaptiveQuestionTrigger:
    """
    Determines when to trigger adaptive questioning.
    
    TRIGGER CONDITIONS (ANY):
        1. confidence_score < 0.6
        2. contradiction_penalty > 0.4
        3. speed_penalty > 0.5 AND uniformity_penalty > 0.3
    
    NON-TRIGGER CONDITIONS (SKIP):
        1. confidence_score >= 0.8
        2. User has already completed adaptive questions
        3. User opted out of adaptive questions
    """
    
    def should_trigger(
        self,
        confidence_score: float,
        confidence_breakdown: Dict[str, float],
        user_preferences: Dict[str, bool],
        session_state: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Check if adaptive questioning should be triggered.
        
        Returns:
            (should_trigger: bool, reason: str)
        """
        # Check skip conditions first
        if user_preferences.get("opt_out_adaptive", False):
            return False, "user_opted_out"
        
        if session_state.get("adaptive_completed", False):
            return False, "already_completed"
        
        if confidence_score >= 0.8:
            return False, "confidence_sufficient"
        
        # Check trigger conditions
        breakdown = confidence_breakdown
        
        if confidence_score < 0.6:
            return True, "low_overall_confidence"
        
        if breakdown.get("contradiction_penalty", 0) > 0.4:
            return True, "high_contradiction"
        
        if breakdown.get("speed_penalty", 0) > 0.5 and breakdown.get("uniformity_penalty", 0) > 0.3:
            return True, "speed_uniformity_compound"
        
        return False, "no_trigger_condition"
```

---

## V. Integration Points in Pipeline

### 5.1 Pipeline Integration Diagram

```
DecisionController.run_pipeline()
│
├── Stage 1: Input Normalize
│   └── ConsistencyValidator.validate_raw_input()  ◄── NEW
│       └── Returns: confidence_breakdown, initial_confidence
│
├── Stage 1.5: ADAPTIVE BRANCHING  ◄── NEW STAGE
│   └── IF initial_confidence < threshold:
│       ├── AdaptiveQuestionInjector.select_questions()
│       ├── RETURN partial response with questions
│       └── AWAIT user responses
│       └── ConsistencyValidator.recompute_confidence()
│
├── Stage 2: Feature Extraction (unchanged)
│
├── Stage 3: Merge (unchanged)
│
├── Stage 4: SIMGR Scoring  ◄── UNCHANGED (FROZEN)
│   │
│   │   ┌─────────────────────────────────────────────┐
│   │   │ SCORING BOUNDARY                            │
│   │   │                                             │
│   │   │ confidence_score IS NOT USED HERE           │
│   │   │ Only: skills, interests, education,         │
│   │   │       ability_score, career data            │
│   │   │                                             │
│   │   │ SIMGRScorer receives:                       │
│   │   │   user_profile (NO confidence_score field)  │
│   │   │   careers                                   │
│   │   │                                             │
│   │   └─────────────────────────────────────────────┘
│   │
│
├── Stage 5: Rule Engine (unchanged)
│
├── Stage 6: Market Data (unchanged)
│
├── Stage 7: Explanation Layer
│   └── ExplanationDegradationStrategy.apply()  ◄── NEW
│       └── Degrades explanation if confidence < 0.6
│
└── Response Assembly
    └── Includes: quality_flags, confidence_score, confidence_breakdown  ◄── NEW
```

### 5.2 Code Integration

```python
# backend/api/controllers/decision_controller.py

class DecisionController:
    """Extended with consistency validation."""
    
    async def run_pipeline(self, request: DecisionRequest) -> DecisionResponse:
        # ... existing setup ...
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 1: Input Normalize
        # ═══════════════════════════════════════════════════════════════
        normalized_input = self._normalize_input(request)
        stages_completed.append("input_normalize")
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 1.5: Consistency Validation (NEW)
        # ═══════════════════════════════════════════════════════════════
        from backend.quality.consistency_validator import ConsistencyValidator
        from backend.quality.adaptive_questions import AdaptiveQuestionTrigger
        
        validator = ConsistencyValidator()
        confidence_result = validator.validate(
            response_times=request.response_metadata.get("timestamps", []),
            likert_responses=request.raw_responses.get("likert", []),
            trait_responses=request.raw_responses.get("traits", {}),
        )
        
        confidence_score = confidence_result["confidence_score"]
        confidence_breakdown = confidence_result["breakdown"]
        quality_flags = self._policy.get_quality_flags(confidence_score)
        
        stages_completed.append("consistency_validation")
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 1.6: Adaptive Question Check (NEW)
        # ═══════════════════════════════════════════════════════════════
        trigger = AdaptiveQuestionTrigger()
        should_adapt, reason = trigger.should_trigger(
            confidence_score, confidence_breakdown,
            request.user_preferences, request.session_state
        )
        
        if should_adapt and not request.is_adaptive_response:
            # Return partial response requesting adaptive questions
            adaptive_questions = self._injector.select_questions(
                confidence_breakdown, self._adaptive_config
            )
            return DecisionResponse(
                trace_id=trace_id,
                status="AWAITING_ADAPTIVE",
                adaptive_questions=adaptive_questions,
                partial_confidence=confidence_score,
                # ... minimal other fields ...
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 4: SIMGR Scoring (UNCHANGED - AUTHORITY)
        # ═══════════════════════════════════════════════════════════════
        # NOTE: confidence_score NOT passed to scoring
        rankings = await self._run_scoring(merged_profile, trace_id)
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 7: Explanation Layer (ENHANCED)
        # ═══════════════════════════════════════════════════════════════
        explanation = await self._generate_explanation(...)
        
        # Apply degradation based on confidence
        explanation = self._degradation_strategy.apply(
            explanation, confidence_score, self._policy
        )
        
        # ═══════════════════════════════════════════════════════════════
        # BUILD RESPONSE (ENHANCED)
        # ═══════════════════════════════════════════════════════════════
        response = DecisionResponse(
            # ... existing fields ...
            quality_assessment=QualityAssessment(
                confidence_score=confidence_score,
                confidence_breakdown=confidence_breakdown,
                quality_flags=quality_flags,
                explanation_mode=self._policy.get_explanation_mode(confidence_score),
            ),
        )
```

### 5.3 Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         DATA QUALITY ENHANCEMENT FLOW                         │
│                                                                               │
│  ┌───────────┐    ┌─────────────────┐    ┌──────────────────────────────────┐│
│  │Raw Survey │───▶│ Consistency     │───▶│ confidence_score = 0.72          ││
│  │Responses  │    │ Validator       │    │ breakdown:                       ││
│  │+ Timing   │    │                 │    │   speed_penalty: 0.15            ││
│  └───────────┘    │ ┌─────────────┐ │    │   contradiction_penalty: 0.18   ││
│                   │ │Speed Detect │ │    │   uniformity_penalty: 0.12      ││
│                   │ └─────────────┘ │    │   entropy_penalty: 0.08         ││
│                   │ ┌─────────────┐ │    └──────────────────────────────────┘│
│                   │ │Contradiction│ │                  │                     │
│                   │ │Matrix       │ │                  ▼                     │
│                   │ └─────────────┘ │    ┌──────────────────────────────────┐│
│                   │ ┌─────────────┐ │    │ Threshold Policy                 ││
│                   │ │Likert Unif. │ │    │   0.72 >= 0.6 → FULL explanation ││
│                   │ └─────────────┘ │    │   0.72 >= 0.7 → No flag          ││
│                   │ ┌─────────────┐ │    │   0.72 >= 0.6 → Skip adaptive    ││
│                   │ │Entropy      │ │    └──────────────────────────────────┘│
│                   │ └─────────────┘ │                  │                     │
│                   └─────────────────┘                  │                     │
│                                                        ▼                     │
│  ════════════════════════════════════════════════════════════════════════   │
│  ║                    SCORING BOUNDARY (IMPERMEABLE)                    ║   │
│  ════════════════════════════════════════════════════════════════════════   │
│                                        │                                     │
│                                        ▼                                     │
│                    ┌──────────────────────────────────────┐                 │
│                    │           SIMGRScorer                │                 │
│                    │                                      │                 │
│                    │  INPUT:                              │                 │
│                    │    skills: [...]                     │                 │
│                    │    interests: [...]                  │                 │
│                    │    education_level: "..."            │                 │
│                    │    ability_score: 0.75               │                 │
│                    │                                      │                 │
│                    │  ❌ confidence_score NOT USED       │                 │
│                    │                                      │                 │
│                    │  OUTPUT:                             │                 │
│                    │    ranked_careers: [...]             │                 │
│                    │    total_score: 0.8234               │                 │
│                    │                                      │                 │
│                    └──────────────────────────────────────┘                 │
│                                        │                                     │
│  ════════════════════════════════════════════════════════════════════════   │
│                                        │                                     │
│                                        ▼                                     │
│                    ┌──────────────────────────────────────┐                 │
│                    │       Explanation Layer              │                 │
│                    │                                      │                 │
│                    │  USES confidence_score:              │                 │
│                    │    - Degrade if < 0.6                │                 │
│                    │    - Add disclaimer if < 0.4         │                 │
│                    │                                      │                 │
│                    └──────────────────────────────────────┘                 │
│                                        │                                     │
│                                        ▼                                     │
│                    ┌──────────────────────────────────────┐                 │
│                    │         Final Response               │                 │
│                    │                                      │                 │
│                    │  rankings: [...] (UNCHANGED)         │                 │
│                    │  explanation: {...} (maybe degraded) │                 │
│                    │  quality_assessment:                 │                 │
│                    │    confidence_score: 0.72            │                 │
│                    │    quality_flags: []                 │                 │
│                    │    explanation_mode: "full"          │                 │
│                    │                                      │                 │
│                    └──────────────────────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## VI. Summary

### Key Guarantees

| Property | Guarantee |
|----------|-----------|
| Scoring Determinism | SIMGRScorer NEVER modified |
| Score Isolation | Confidence score NEVER used in base score calculation |
| Confidence Scope | Only affects: explanation, flagging, adaptive trigger |
| Adaptive Limits | Maximum 5 additional questions |
| No Hidden Defaults | All thresholds and weights explicit |

### File Structure (New)

```
backend/quality/
├── __init__.py
├── consistency_validator.py    # Main validator + aggregator
├── detectors/
│   ├── __init__.py
│   ├── speed_anomaly.py
│   ├── trait_contradiction.py
│   ├── likert_uniformity.py
│   └── entropy_analyzer.py
├── adaptive_questions.py       # Question injection logic
├── confidence_policy.py        # Threshold definitions
└── explanation_degradation.py  # Degradation strategy
```

### Integration Checklist

- [ ] Create `backend/quality/` module structure
- [ ] Implement 4 detectors with unit tests
- [ ] Implement confidence aggregator
- [ ] Add AdaptiveQuestionInjector with question bank
- [ ] Update DecisionController with new stages
- [ ] Update DecisionResponse model with QualityAssessment
- [ ] Integrate degradation into explanation layer
- [ ] Add monitoring metrics for confidence distribution
- [ ] Write integration tests verifying scoring isolation
