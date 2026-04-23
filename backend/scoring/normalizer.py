# backend/scoring/normalizer.py
"""
Numerical normalization & similarity utilities.

Provides safe, deterministic utilities for:
- Clamping values to ranges
- Normalizing lists/vectors
- Computing similarities
- Weighted aggregation
"""

from __future__ import annotations

from typing import Iterable, Sequence, Set, Union, TYPE_CHECKING
import math

if TYPE_CHECKING:
    from backend.scoring.models import UserProfile

Number = Union[int, float]


class DataNormalizer:
    """Utilities for normalizing and comparing numerical data.
    
    All operations are:
    - Deterministic (no randomness)
    - Safe (handle NaN, Inf, None gracefully)
    - Stateless (pure functions)
    """
    
    # Epsilon for near-zero comparisons
    EPS = 1e-9
    
    # =====================================================
    # Validation
    # =====================================================
    
    @staticmethod
    def _is_valid_number(x: Number) -> bool:
        """Check if x is a finite numeric value.
        
        Args:
            x: Value to check
        
        Returns:
            True if x is finite number, False otherwise
        """
        if x is None:
            return False
        
        if not isinstance(x, (int, float)):
            return False
        
        return math.isfinite(x)
    
    # =====================================================
    # Clamping
    # =====================================================
    
    @staticmethod
    def clamp(
        value: Number,
        min_val: Number = 0.0,
        max_val: Number = 1.0,
    ) -> float:
        """Clamp value between bounds safely.
        
        Properties:
        - Handles NaN gracefully (returns min_val)
        - Handles Inf gracefully (returns max_val)
        - Returns min_val if input invalid
        - Always returns float
        
        Args:
            value: Value to clamp
            min_val: Lower bound (default 0.0)
            max_val: Upper bound (default 1.0)
        
        Returns:
            Clamped value in [min_val, max_val]
        """
        if value is None or not isinstance(value, (int, float)):
            return float(min_val)
        
        # Handle infinity: positive inf goes to max, negative inf goes to min
        if math.isinf(value):
            return float(max_val) if value > 0 else float(min_val)
        
        # Handle NaN: return min_val
        if math.isnan(value):
            return float(min_val)
        
        return float(max(min_val, min(max_val, value)))
    
    # =====================================================
    # Range Normalization
    # =====================================================
    
    @staticmethod
    def normalize_to_range(
        value: Number,
        min_val: Number,
        max_val: Number,
        target_min: Number = 0.0,
        target_max: Number = 1.0,
    ) -> float:
        """Normalize value from [min_val, max_val] → [target_min, target_max].
        
        Properties:
        - Handles edge cases (equal min/max, invalid input)
        - Returns midpoint if range too small
        - Clamps result to target range
        
        Args:
            value: Value to normalize
            min_val: Source lower bound
            max_val: Source upper bound
            target_min: Target lower bound (default 0.0)
            target_max: Target upper bound (default 1.0)
        
        Returns:
            Normalized value in [target_min, target_max]
        """
        # Validate all inputs
        if not all(
            DataNormalizer._is_valid_number(v)
            for v in (value, min_val, max_val, target_min, target_max)
        ):
            return float(target_min)
        
        # Handle degenerate case (min == max)
        if abs(max_val - min_val) < DataNormalizer.EPS:
            return float((target_min + target_max) / 2)
        
        # Normalize to [0, 1] then scale to target range
        ratio = (value - min_val) / (max_val - min_val)
        scaled = ratio * (target_max - target_min) + target_min
        
        # Clamp to target range
        return DataNormalizer.clamp(scaled, target_min, target_max)
    
    @staticmethod
    def normalize_list(values: Iterable[Number]) -> list[float]:
        """Normalize iterable of numbers to [0, 1].
        
        Properties:
        - Filters out invalid values
        - Returns [0.5, 0.5, ...] if all values equal
        - Empty input returns []
        
        Args:
            values: Iterable of numbers
        
        Returns:
            List of values normalized to [0, 1]
        """
        if values is None:
            return []
        
        # Filter valid values
        clean = [
            float(v)
            for v in values
            if DataNormalizer._is_valid_number(v)
        ]
        
        if not clean:
            return []
        
        min_val = min(clean)
        max_val = max(clean)
        
        # Handle degenerate case
        if abs(max_val - min_val) < DataNormalizer.EPS:
            return [0.5] * len(clean)
        
        # Normalize each value
        return [
            DataNormalizer.normalize_to_range(v, min_val, max_val)
            for v in clean
        ]
    
    # =====================================================
    # Similarities
    # =====================================================
    
    @staticmethod
    def jaccard_similarity(
        set1: Set[str],
        set2: Set[str],
    ) -> float:
        """Jaccard similarity coefficient in [0, 1].
        
        Jaccard = |intersection| / |union|
        
        Properties:
        - Returns 0.0 if either set empty
        - Returns 1.0 if sets identical
        - Deterministic and stateless
        
        Args:
            set1: First set
            set2: Second set
        
        Returns:
            Jaccard similarity in [0, 1]
        """
        if not set1 or not set2:
            return 0.0
        
        union = set1 | set2
        
        if not union:
            return 0.0
        
        intersection = set1 & set2
        return len(intersection) / len(union)
    
    @staticmethod
    def cosine_similarity(
        vec1: Sequence[Number],
        vec2: Sequence[Number],
    ) -> float:
        """Cosine similarity with numerical safety.
        
        sim(u,v) = (u·v) / (||u|| ||v||)
        
        Properties:
        - Handles NaN, Inf gracefully
        - Returns 0.0 if vectors zero-length
        - Clamps result to [-1, 1]
        
        Args:
            vec1: First vector
            vec2: Second vector
        
        Returns:
            Cosine similarity in [-1, 1]
        
        Raises:
            ValueError: If vector lengths differ
        """
        if vec1 is None or vec2 is None:
            return 0.0
        
        if len(vec1) != len(vec2):
            raise ValueError("Vector length mismatch")
        
        if not vec1:
            return 0.0
        
        # Compute dot product and norms safely
        dot = 0.0
        norm1_sq = 0.0
        norm2_sq = 0.0
        
        for a, b in zip(vec1, vec2):
            # Skip invalid values
            if not (
                DataNormalizer._is_valid_number(a)
                and DataNormalizer._is_valid_number(b)
            ):
                continue
            
            a = float(a)
            b = float(b)
            
            dot += a * b
            norm1_sq += a * a
            norm2_sq += b * b
        
        # Handle zero norm (degenerate vectors)
        if norm1_sq < DataNormalizer.EPS or norm2_sq < DataNormalizer.EPS:
            return 0.0
        
        # Compute similarity
        sim = dot / (math.sqrt(norm1_sq) * math.sqrt(norm2_sq))
        
        # Clamp to [-1, 1] (handle numerical errors)
        return DataNormalizer.clamp(sim, -1.0, 1.0)
    
    # =====================================================
    # Aggregation
    # =====================================================

    @staticmethod
    def weighted_average(
        values: Iterable[Number],
        weights: Iterable[Number],
    ) -> float:
        """Safe weighted average of values.

        weighted_avg = Σ(value * weight) / Σ(weight)

        Properties:
        - Skips invalid value/weight pairs
        - Returns 0.0 if no valid pairs
        - Returns 0.0 if total weight is zero

        Args:
            values: Values to average
            weights: Weights (must align with values)

        Returns:
            Weighted average
        """
        if values is None or weights is None:
            return 0.0

        # Zip and filter valid pairs
        pairs = [
            (float(v), float(w))
            for v, w in zip(values, weights)
            if (
                DataNormalizer._is_valid_number(v)
                and DataNormalizer._is_valid_number(w)
            )
        ]

        if not pairs:
            return 0.0

        total_weight = sum(w for _, w in pairs)

        # Handle zero total weight
        if abs(total_weight) < DataNormalizer.EPS:
            return 0.0

        weighted_sum = sum(v * w for v, w in pairs)

        return weighted_sum / total_weight


# =====================================================
# Prompt3 Pipeline Integration
# =====================================================

class Prompt3Normalizer:
    """Normalizer for Prompt3 output to UserProfile.

    Handles the pipeline: analyze.py → process_user_profile → normalized UserProfile → scoring
    """

    @staticmethod
    def normalize_user_profile_from_analyze(
        analyze_output: dict
    ):
        """Convert analyze.py output to UserProfile.

        Args:
            analyze_output: Output from process_user_profile() with keys:
                - age: int
                - education_level: str
                - interest_tags: List[str]
                - skill_tags: List[str]
                - goal_cleaned: str
                - intent: str
                - chat_summary: str
                - confidence_score: float

        Returns:
            Normalized UserProfile

        Raises:
            ValueError: If required fields missing or invalid
        """
        from backend.scoring.models import UserProfile  # Import here to avoid circular import

        # Validate required fields
        required_fields = [
            "age", "education_level", "interest_tags",
            "skill_tags", "goal_cleaned", "intent",
            "chat_summary", "confidence_score"
        ]

        missing = [f for f in required_fields if f not in analyze_output]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # Extract and validate
        age = analyze_output["age"]
        if not isinstance(age, int) or age < 0:
            raise ValueError(f"Invalid age: {age}")

        education_level = str(analyze_output["education_level"]).strip()
        interest_tags = analyze_output["interest_tags"]
        if not isinstance(interest_tags, list):
            raise ValueError(f"interest_tags must be list, got {type(interest_tags)}")

        skill_tags = analyze_output["skill_tags"]
        if not isinstance(skill_tags, list):
            raise ValueError(f"skill_tags must be list, got {type(skill_tags)}")

        confidence_score = analyze_output["confidence_score"]
        if not isinstance(confidence_score, (int, float)) or not (0.0 <= confidence_score <= 1.0):
            raise ValueError(f"confidence_score must be float in [0,1], got {confidence_score}")

        # Create UserProfile
        # Note: ability_score derived from confidence_score
        return UserProfile(
            skills=skill_tags,
            interests=interest_tags,
            education_level=education_level,
            ability_score=confidence_score,  # Map confidence to ability
            confidence_score=confidence_score,
        )

    @staticmethod
    def validate_analyze_output(analyze_output: dict) -> bool:
        """Validate analyze output schema.

        Args:
            analyze_output: Output to validate

        Returns:
            True if valid, raises ValueError if invalid
        """
        try:
            Prompt3Normalizer.normalize_user_profile_from_analyze(analyze_output)
            return True
        except ValueError as e:
            raise ValueError(f"Invalid analyze output: {e}")

