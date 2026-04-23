# backend/explanation/minimal_explanation.py
"""
Minimal UI Explanation Layer
============================

Optimized explanation generation for minimal UI system.

CONSTRAINTS:
1. Explanation derives STRICTLY from computed data:
   - Score breakdown (SIMGR components)
   - Rule trace (RuleEngine audit trail)
   - Feature vector (input features)
2. NO hallucination - all content is data-driven
3. NO additional reasoning beyond computed result
4. Single LLM formatting call (cost control)
5. No interactive chat

TIERS:
- Tier 1 (Default): Summary fit, top 3 components, trait alignment
- Tier 2 (On-demand): Weights, trade-offs, sensitivity simulation

INVARIANT: Output is 100% traceable to input data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("explanation.minimal")


# ==============================================================================
# I. EXPLANATION DATA SOURCES
# ==============================================================================

@dataclass(frozen=True)
class ScoreBreakdownSource:
    """
    Score breakdown from SIMGRScorer.
    
    SOURCE: backend/scoring/scoring.py → ScoreBreakdown
    """
    study_score: float
    interest_score: float
    market_score: float
    growth_score: float
    risk_score: float
    final_score: float
    
    # Optional details from components
    study_details: Optional[Dict[str, Any]] = None
    interest_details: Optional[Dict[str, Any]] = None
    market_details: Optional[Dict[str, Any]] = None
    growth_details: Optional[Dict[str, Any]] = None
    risk_details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "study": self.study_score,
            "interest": self.interest_score,
            "market": self.market_score,
            "growth": self.growth_score,
            "risk": self.risk_score,
            "final": self.final_score,
        }
    
    def get_ranked_components(self) -> List[Tuple[str, float]]:
        """Return components sorted by score (descending)."""
        components = [
            ("study", self.study_score),
            ("interest", self.interest_score),
            ("market", self.market_score),
            ("growth", self.growth_score),
            ("risk", self.risk_score),
        ]
        return sorted(components, key=lambda x: x[1], reverse=True)


@dataclass(frozen=True)
class RuleTraceSource:
    """
    Rule execution trace from RuleEngine.
    
    SOURCE: backend/flow/invariants.py → RuleEngineGuard
    """
    rules_applied: List[str] = field(default_factory=list)
    rule_scores: Dict[str, float] = field(default_factory=dict)
    flags: Dict[str, bool] = field(default_factory=dict)
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_triggered_rules(self) -> List[str]:
        """Return list of rules that fired."""
        return [r for r in self.rules_applied if r]
    
    def get_flag_summary(self) -> Dict[str, bool]:
        """Return flags set by rules."""
        return dict(self.flags)


@dataclass(frozen=True)
class FeatureVectorSource:
    """
    Input feature vector for explanation grounding.
    
    SOURCE: backend/scoring/models.py → UserProfile + CareerData
    """
    user_skills: List[str] = field(default_factory=list)
    user_interests: List[str] = field(default_factory=list)
    education_level: str = ""
    ability_score: float = 0.5
    confidence_score: float = 0.5
    
    career_name: str = ""
    career_required_skills: List[str] = field(default_factory=list)
    career_market_data: Optional[Dict[str, Any]] = None
    
    def get_skill_overlap(self) -> Tuple[List[str], List[str]]:
        """Return (matched_skills, missing_skills)."""
        user_set = set(s.lower() for s in self.user_skills)
        req_set = set(s.lower() for s in self.career_required_skills)
        matched = list(user_set & req_set)
        missing = list(req_set - user_set)
        return matched, missing
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skills": self.user_skills,
            "interests": self.user_interests,
            "education": self.education_level,
            "ability": self.ability_score,
            "confidence": self.confidence_score,
            "career": self.career_name,
            "required_skills": self.career_required_skills,
        }


# ==============================================================================
# II. TIER DEFINITIONS
# ==============================================================================

class ExplanationTier(Enum):
    """Explanation detail tiers."""
    TIER_1_DEFAULT = auto()    # Default: summary + top 3 + traits
    TIER_2_ONDEMAND = auto()   # On-demand: weights + trade-offs + sensitivity


@dataclass(frozen=True)
class Tier1Content:
    """
    Tier 1 (Default) explanation content.
    
    Contains:
    - Summary fit statement
    - Top 3 score components
    - Trait alignment description
    
    NO LLM generation - pure data extraction.
    """
    summary_fit: str
    top_3_components: List[Tuple[str, float, str]]  # (name, score, explanation)
    trait_alignment: str
    career_name: str
    final_score: float
    
    # Provenance tracking
    source_hash: str = ""


@dataclass(frozen=True)
class Tier2Content:
    """
    Tier 2 (On-demand) explanation content.
    
    Contains:
    - Weight contribution breakdown
    - Trade-off analysis
    - Sensitivity simulation (±10% weight)
    
    NO LLM generation - pure computation.
    """
    weight_contributions: Dict[str, Dict[str, float]]  # {component: {weight, score, contribution}}
    trade_off_analysis: List[Dict[str, Any]]
    sensitivity_simulation: Dict[str, Dict[str, float]]  # {component: {-10%, base, +10%}}
    
    # Provenance tracking
    source_hash: str = ""


# ==============================================================================
# III. EXPLANATION GENERATOR (NO LLM IN CORE LOGIC)
# ==============================================================================

# Frozen weights from SIMGRScorer
FROZEN_WEIGHTS = {
    "study": 0.30,
    "interest": 0.25,
    "market": 0.25,
    "growth": 0.10,
    "risk": 0.10,
}

# Component names for display
COMPONENT_DISPLAY_NAMES = {
    "study": "Study Fit",
    "interest": "Interest Match",
    "market": "Market Demand",
    "growth": "Growth Potential",
    "risk": "Risk Profile",
}

# Template explanations (data-driven, NO hallucination)
SCORE_TEMPLATES = {
    "high": "{name} is strong ({score:.0%}) - {reason}",
    "medium": "{name} is moderate ({score:.0%}) - {reason}",
    "low": "{name} is limited ({score:.0%}) - {reason}",
}


class Tier1Generator:
    """
    Generates Tier 1 (Default) explanations.
    
    CONSTRAINT: All output derived strictly from:
    - ScoreBreakdownSource
    - RuleTraceSource
    - FeatureVectorSource
    
    NO hallucination. NO additional reasoning.
    """
    
    def __init__(
        self,
        score_breakdown: ScoreBreakdownSource,
        rule_trace: RuleTraceSource,
        feature_vector: FeatureVectorSource,
    ):
        self._breakdown = score_breakdown
        self._trace = rule_trace
        self._features = feature_vector
        
        # Compute source hash for provenance
        self._source_hash = self._compute_source_hash()
    
    def _compute_source_hash(self) -> str:
        """Compute hash of all source data for traceability."""
        data = {
            "breakdown": self._breakdown.to_dict(),
            "rules": self._trace.rules_applied,
            "features": self._features.to_dict(),
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]
    
    def generate(self) -> Tier1Content:
        """
        Generate Tier 1 explanation content.
        
        Returns:
            Tier1Content with data-derived explanations
        """
        # 1. Summary Fit
        summary = self._generate_summary_fit()
        
        # 2. Top 3 Components
        top_3 = self._generate_top_3_components()
        
        # 3. Trait Alignment
        traits = self._generate_trait_alignment()
        
        return Tier1Content(
            summary_fit=summary,
            top_3_components=top_3,
            trait_alignment=traits,
            career_name=self._features.career_name,
            final_score=self._breakdown.final_score,
            source_hash=self._source_hash,
        )
    
    def _generate_summary_fit(self) -> str:
        """
        Generate summary fit statement.
        
        TEMPLATE-BASED: No hallucination.
        """
        score = self._breakdown.final_score
        career = self._features.career_name
        
        if score >= 0.75:
            return f"Strong fit for {career} (score: {score:.0%})"
        elif score >= 0.50:
            return f"Moderate fit for {career} (score: {score:.0%})"
        elif score >= 0.30:
            return f"Potential fit for {career} (score: {score:.0%})"
        else:
            return f"Limited fit for {career} (score: {score:.0%})"
    
    def _generate_top_3_components(self) -> List[Tuple[str, float, str]]:
        """
        Generate explanations for top 3 score components.
        
        DATA-DRIVEN: Explanations reference actual input data.
        """
        ranked = self._breakdown.get_ranked_components()[:3]
        result = []
        
        for component, score in ranked:
            explanation = self._explain_component(component, score)
            display_name = COMPONENT_DISPLAY_NAMES.get(component, component)
            result.append((display_name, score, explanation))
        
        return result
    
    def _explain_component(self, component: str, score: float) -> str:
        """
        Generate data-driven explanation for a component.
        
        NO hallucination - references actual feature values.
        """
        if component == "study":
            matched, missing = self._features.get_skill_overlap()
            if matched:
                return f"Skills match: {', '.join(matched[:3])}"
            elif missing:
                return f"Skills gap: {', '.join(missing[:3])}"
            return "Skills data unavailable"
        
        elif component == "interest":
            interests = self._features.user_interests[:3]
            if interests:
                return f"Interest alignment: {', '.join(interests)}"
            return "Interest data unavailable"
        
        elif component == "market":
            market = self._features.career_market_data or {}
            demand = market.get("demand_level", "unknown")
            return f"Market demand: {demand}"
        
        elif component == "growth":
            market = self._features.career_market_data or {}
            growth = market.get("growth_projection", "unknown")
            return f"Growth projection: {growth}"
        
        elif component == "risk":
            market = self._features.career_market_data or {}
            risk = market.get("stability", "unknown")
            return f"Stability: {risk}"
        
        return "Data unavailable"
    
    def _generate_trait_alignment(self) -> str:
        """
        Generate trait alignment statement.
        
        DATA-DRIVEN: Based on feature vector analysis.
        """
        matched, _ = self._features.get_skill_overlap()
        interests = self._features.user_interests
        
        traits = []
        if matched:
            traits.append(f"{len(matched)} skill matches")
        if interests:
            traits.append(f"{len(interests)} interest areas")
        
        if traits:
            return f"Profile alignment: {', '.join(traits)}"
        return "Limited profile data for alignment analysis"


class Tier2Generator:
    """
    Generates Tier 2 (On-demand) explanations.
    
    CONSTRAINT: Pure computation - no LLM, no hallucination.
    """
    
    def __init__(
        self,
        score_breakdown: ScoreBreakdownSource,
        rule_trace: RuleTraceSource,
        feature_vector: FeatureVectorSource,
        weights: Optional[Dict[str, float]] = None,
    ):
        self._breakdown = score_breakdown
        self._trace = rule_trace
        self._features = feature_vector
        self._weights = weights or FROZEN_WEIGHTS
        
        # Compute source hash
        self._source_hash = self._compute_source_hash()
    
    def _compute_source_hash(self) -> str:
        """Compute hash for provenance."""
        data = {
            "breakdown": self._breakdown.to_dict(),
            "weights": self._weights,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]
    
    def generate(self) -> Tier2Content:
        """
        Generate Tier 2 explanation content.
        
        Returns:
            Tier2Content with computed analysis
        """
        # 1. Weight Contributions
        contributions = self._compute_weight_contributions()
        
        # 2. Trade-off Analysis
        tradeoffs = self._compute_tradeoff_analysis()
        
        # 3. Sensitivity Simulation
        sensitivity = self._compute_sensitivity_simulation()
        
        return Tier2Content(
            weight_contributions=contributions,
            trade_off_analysis=tradeoffs,
            sensitivity_simulation=sensitivity,
            source_hash=self._source_hash,
        )
    
    def _compute_weight_contributions(self) -> Dict[str, Dict[str, float]]:
        """
        Compute weight contribution for each component.
        
        contribution = weight × score
        """
        scores = self._breakdown.to_dict()
        result = {}
        
        for component, weight in self._weights.items():
            score = scores.get(component, 0.0)
            contribution = weight * score
            result[component] = {
                "weight": weight,
                "score": score,
                "contribution": round(contribution, 4),
                "percentage": round((contribution / max(scores["final"], 0.001)) * 100, 1),
            }
        
        return result
    
    def _compute_tradeoff_analysis(self) -> List[Dict[str, Any]]:
        """
        Compute trade-offs between top components.
        
        Analysis: If component A improves, what happens to rank?
        """
        scores = self._breakdown.to_dict()
        tradeoffs = []
        
        # Find weakest and strongest components
        components = [(k, v) for k, v in scores.items() if k != "final"]
        components.sort(key=lambda x: x[1])
        
        if len(components) >= 2:
            weakest = components[0]
            strongest = components[-1]
            
            # Trade-off: improving weakest
            improvement_needed = strongest[1] - weakest[1]
            tradeoffs.append({
                "type": "improvement_opportunity",
                "target": weakest[0],
                "current": weakest[1],
                "gap": round(improvement_needed, 3),
                "impact": f"Improving {weakest[0]} by {improvement_needed:.0%} would match {strongest[0]}",
            })
        
        return tradeoffs
    
    def _compute_sensitivity_simulation(self) -> Dict[str, Dict[str, float]]:
        """
        Compute sensitivity analysis: what if weight ±10%?
        
        DETERMINISTIC: Pure arithmetic, no randomness.
        """
        scores = self._breakdown.to_dict()
        sensitivity = {}
        
        for component, base_weight in self._weights.items():
            score = scores.get(component, 0.0)
            
            # Compute adjusted contributions
            weight_minus_10 = base_weight * 0.90
            weight_plus_10 = base_weight * 1.10
            
            # Recompute final score with adjusted weight
            base_contrib = base_weight * score
            minus_contrib = weight_minus_10 * score
            plus_contrib = weight_plus_10 * score
            
            # Delta from base contribution
            sensitivity[component] = {
                "weight_base": base_weight,
                "weight_minus_10pct": round(weight_minus_10, 4),
                "weight_plus_10pct": round(weight_plus_10, 4),
                "contribution_base": round(base_contrib, 4),
                "contribution_minus_10pct": round(minus_contrib, 4),
                "contribution_plus_10pct": round(plus_contrib, 4),
                "delta_minus": round(minus_contrib - base_contrib, 4),
                "delta_plus": round(plus_contrib - base_contrib, 4),
            }
        
        return sensitivity


# ==============================================================================
# IV. LLM FORMATTER (SINGLE CALL - COST CONTROLLED)
# ==============================================================================

@dataclass
class LLMFormatRequest:
    """
    Request for single LLM formatting call.
    
    CONSTRAINT: Only 1 LLM call allowed.
    CONSTRAINT: No interactive chat.
    """
    tier_1: Tier1Content
    tier_2: Optional[Tier2Content] = None
    target_format: str = "natural_language"
    max_tokens: int = 300


class LLMFormatter:
    """
    LLM formatter with strict cost control.
    
    CONSTRAINTS:
    - Only 1 LLM call per explanation
    - No interactive chat
    - Template-first, LLM-second fallback
    
    OPTIMIZATION: Try template formatting first. Only call LLM if
    template output is insufficient.
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        enable_llm: bool = True,
    ):
        self._llm_client = llm_client
        self._enable_llm = enable_llm
        self._call_count = 0
        self._max_calls = 1  # HARD LIMIT
    
    def format_explanation(
        self,
        request: LLMFormatRequest,
    ) -> Dict[str, Any]:
        """
        Format explanation with cost control.
        
        Strategy:
        1. Always generate template-based output first
        2. If LLM enabled and under limit, enhance with single LLM call
        3. Return formatted result with provenance
        
        Returns:
            Formatted explanation dict
        """
        # Step 1: Template-based formatting (always works, no LLM)
        template_output = self._format_with_template(request.tier_1, request.tier_2)
        
        # Step 2: LLM enhancement (if enabled and under limit)
        if self._enable_llm and self._llm_client and self._call_count < self._max_calls:
            llm_output = self._format_with_llm(request, template_output)
            self._call_count += 1
            return llm_output
        
        return template_output
    
    def _format_with_template(
        self,
        tier_1: Tier1Content,
        tier_2: Optional[Tier2Content],
    ) -> Dict[str, Any]:
        """
        Format using templates only (no LLM).
        
        ALWAYS succeeds - no external dependencies.
        """
        output = {
            "tier": "tier_1",
            "career": tier_1.career_name,
            "score": tier_1.final_score,
            "summary": tier_1.summary_fit,
            "top_components": [
                {"name": name, "score": score, "reason": reason}
                for name, score, reason in tier_1.top_3_components
            ],
            "trait_alignment": tier_1.trait_alignment,
            "source_hash": tier_1.source_hash,
            "format_method": "template",
            "llm_calls": 0,
        }
        
        # Add Tier 2 if available
        if tier_2:
            output["tier"] = "tier_2"
            output["weight_analysis"] = tier_2.weight_contributions
            output["tradeoffs"] = tier_2.trade_off_analysis
            output["sensitivity"] = tier_2.sensitivity_simulation
            output["tier_2_source_hash"] = tier_2.source_hash
        
        return output
    
    def _format_with_llm(
        self,
        request: LLMFormatRequest,
        template_base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Enhance with single LLM call.
        
        IMPORTANT: This is a FORMATTING call only.
        - No new information generated
        - No hallucination allowed
        - Input data passed in prompt for grounding
        """
        # Build LLM prompt with strict grounding
        prompt = self._build_formatting_prompt(request)
        
        try:
            # Single LLM call
            response = self._llm_client.complete(
                prompt=prompt,
                max_tokens=request.max_tokens,
                temperature=0.1,  # Low temperature for consistency
            )
            
            # Parse and validate response
            formatted = self._parse_llm_response(response, template_base)
            formatted["format_method"] = "llm_enhanced"
            formatted["llm_calls"] = 1
            return formatted
            
        except Exception as e:
            logger.warning(f"LLM formatting failed: {e}, using template")
            template_base["format_method"] = "template_fallback"
            template_base["llm_error"] = str(e)
            return template_base
    
    def _build_formatting_prompt(self, request: LLMFormatRequest) -> str:
        """
        Build LLM prompt with strict grounding constraints.
        
        CONSTRAINT: All data provided in prompt - no external lookup.
        """
        tier_1 = request.tier_1
        
        prompt = f"""Format the following career fit explanation into natural language.

CONSTRAINTS:
- Use ONLY the data provided below
- Do NOT add information not in the data
- Do NOT speculate or hallucinate
- Keep response under {request.max_tokens} tokens

DATA:
Career: {tier_1.career_name}
Overall Score: {tier_1.final_score:.0%}
Summary: {tier_1.summary_fit}

Top Components:
"""
        for name, score, reason in tier_1.top_3_components:
            prompt += f"- {name}: {score:.0%} ({reason})\n"
        
        prompt += f"""
Trait Alignment: {tier_1.trait_alignment}

OUTPUT FORMAT:
A clear, concise explanation using ONLY the above data. Do not add any information."""
        
        return prompt
    
    def _parse_llm_response(
        self,
        response: str,
        template_base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse LLM response and merge with template base."""
        result = template_base.copy()
        result["natural_language"] = response.strip()
        return result
    
    def get_call_count(self) -> int:
        """Get number of LLM calls made."""
        return self._call_count
    
    def reset_call_count(self) -> None:
        """Reset call counter (for new explanation request)."""
        self._call_count = 0


# ==============================================================================
# V. UNIFIED EXPLANATION LAYER
# ==============================================================================

class MinimalExplanationLayer:
    """
    Unified explanation layer for minimal UI.
    
    ARCHITECTURE:
    1. Data Sources: ScoreBreakdown, RuleTrace, FeatureVector
    2. Tier 1 (Default): Summary + Top 3 + Traits
    3. Tier 2 (On-demand): Weights + Trade-offs + Sensitivity
    4. LLM Formatter: Single call for natural language (optional)
    
    CONSTRAINTS:
    - No hallucination
    - No additional reasoning
    - Single LLM call max
    - No interactive chat
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        enable_llm: bool = True,
        weights: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize explanation layer.
        
        Args:
            llm_client: Optional LLM client for formatting
            enable_llm: Enable LLM formatting (default: True)
            weights: Optional custom weights (uses FROZEN_WEIGHTS if None)
        """
        self._llm_client = llm_client
        self._enable_llm = enable_llm
        self._weights = weights or FROZEN_WEIGHTS
        self._formatter = LLMFormatter(llm_client, enable_llm)
    
    def explain(
        self,
        score_breakdown: Dict[str, Any],
        rule_trace: Optional[Dict[str, Any]] = None,
        feature_vector: Optional[Dict[str, Any]] = None,
        tier: ExplanationTier = ExplanationTier.TIER_1_DEFAULT,
        format_natural_language: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate explanation for scored career.
        
        Args:
            score_breakdown: Dict with SIMGR scores
            rule_trace: Optional rule execution trace
            feature_vector: Optional input features
            tier: Explanation tier (default or on-demand)
            format_natural_language: Use LLM formatting
        
        Returns:
            Explanation dict with provenance
        """
        # Convert inputs to source objects
        breakdown_src = self._parse_score_breakdown(score_breakdown)
        trace_src = self._parse_rule_trace(rule_trace or {})
        feature_src = self._parse_feature_vector(feature_vector or {})
        
        # Generate Tier 1 (always)
        tier1_gen = Tier1Generator(breakdown_src, trace_src, feature_src)
        tier1_content = tier1_gen.generate()
        
        # Generate Tier 2 (if requested)
        tier2_content = None
        if tier == ExplanationTier.TIER_2_ONDEMAND:
            tier2_gen = Tier2Generator(
                breakdown_src, trace_src, feature_src, self._weights
            )
            tier2_content = tier2_gen.generate()
        
        # Format output
        if format_natural_language:
            request = LLMFormatRequest(
                tier_1=tier1_content,
                tier_2=tier2_content,
            )
            result = self._formatter.format_explanation(request)
        else:
            result = self._formatter._format_with_template(tier1_content, tier2_content)
        
        # Add metadata
        result["tier_requested"] = tier.name
        result["llm_enabled"] = self._enable_llm
        result["weights_used"] = self._weights
        
        return result
    
    def _parse_score_breakdown(self, data: Dict[str, Any]) -> ScoreBreakdownSource:
        """Parse score breakdown dict to source object."""
        return ScoreBreakdownSource(
            study_score=data.get("study_score", data.get("study", 0.0)),
            interest_score=data.get("interest_score", data.get("interest", 0.0)),
            market_score=data.get("market_score", data.get("market", 0.0)),
            growth_score=data.get("growth_score", data.get("growth", 0.0)),
            risk_score=data.get("risk_score", data.get("risk", 0.0)),
            final_score=data.get("final_score", data.get("final", 0.0)),
            study_details=data.get("study_details"),
            interest_details=data.get("interest_details"),
            market_details=data.get("market_details"),
            growth_details=data.get("growth_details"),
            risk_details=data.get("risk_details"),
        )
    
    def _parse_rule_trace(self, data: Dict[str, Any]) -> RuleTraceSource:
        """Parse rule trace dict to source object."""
        return RuleTraceSource(
            rules_applied=data.get("rules_applied", []),
            rule_scores=data.get("rule_scores", {}),
            flags=data.get("flags", {}),
            audit_trail=data.get("audit_trail", []),
        )
    
    def _parse_feature_vector(self, data: Dict[str, Any]) -> FeatureVectorSource:
        """Parse feature vector dict to source object."""
        return FeatureVectorSource(
            user_skills=data.get("skills", data.get("user_skills", [])),
            user_interests=data.get("interests", data.get("user_interests", [])),
            education_level=data.get("education_level", data.get("education", "")),
            ability_score=data.get("ability_score", data.get("ability", 0.5)),
            confidence_score=data.get("confidence_score", data.get("confidence", 0.5)),
            career_name=data.get("career_name", data.get("career", "")),
            career_required_skills=data.get("required_skills", data.get("career_skills", [])),
            career_market_data=data.get("market_data", data.get("career_market", {})),
        )
    
    def explain_batch(
        self,
        careers: List[Dict[str, Any]],
        feature_vector: Optional[Dict[str, Any]] = None,
        tier: ExplanationTier = ExplanationTier.TIER_1_DEFAULT,
    ) -> List[Dict[str, Any]]:
        """
        Generate explanations for multiple careers.
        
        IMPORTANT: Only 1 LLM call total for all careers.
        
        Args:
            careers: List of career dicts with score breakdowns
            feature_vector: Shared feature vector
            tier: Explanation tier
        
        Returns:
            List of explanation dicts
        """
        results = []
        
        # Reset formatter for batch
        self._formatter.reset_call_count()
        
        for i, career in enumerate(careers):
            # Only use LLM for first career (cost control)
            use_llm = (i == 0 and self._enable_llm)
            
            result = self.explain(
                score_breakdown=career.get("scores", career),
                feature_vector=feature_vector,
                tier=tier,
                format_natural_language=use_llm,
            )
            result["batch_index"] = i
            result["batch_llm_used"] = use_llm
            results.append(result)
        
        return results


# ==============================================================================
# VI. CONVENIENCE FUNCTIONS
# ==============================================================================

def create_explanation_layer(
    llm_client: Optional[Any] = None,
    enable_llm: bool = True,
) -> MinimalExplanationLayer:
    """
    Factory function for explanation layer.
    
    Args:
        llm_client: Optional LLM client
        enable_llm: Enable LLM formatting
    
    Returns:
        Configured MinimalExplanationLayer
    """
    return MinimalExplanationLayer(
        llm_client=llm_client,
        enable_llm=enable_llm,
    )


def explain_career(
    score_breakdown: Dict[str, Any],
    feature_vector: Optional[Dict[str, Any]] = None,
    tier: str = "default",
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Convenience function for single career explanation.
    
    Args:
        score_breakdown: Dict with SIMGR scores
        feature_vector: Optional input features
        tier: "default" or "ondemand"
        llm_client: Optional LLM client
    
    Returns:
        Explanation dict
    """
    layer = create_explanation_layer(llm_client)
    tier_enum = (
        ExplanationTier.TIER_2_ONDEMAND
        if tier.lower() == "ondemand"
        else ExplanationTier.TIER_1_DEFAULT
    )
    return layer.explain(
        score_breakdown=score_breakdown,
        feature_vector=feature_vector,
        tier=tier_enum,
    )


# ==============================================================================
# VII. EXAMPLE USAGE
# ==============================================================================

if __name__ == "__main__":
    # Example: Generate explanation for a career
    score_breakdown = {
        "study": 0.82,
        "interest": 0.75,
        "market": 0.68,
        "growth": 0.71,
        "risk": 0.60,
        "final": 0.73,
    }
    
    feature_vector = {
        "skills": ["python", "machine_learning", "data_analysis"],
        "interests": ["AI", "Data Science"],
        "education": "Master",
        "career_name": "Data Scientist",
        "required_skills": ["python", "machine_learning", "statistics", "sql"],
    }
    
    # Create layer (no LLM for demo)
    layer = create_explanation_layer(enable_llm=False)
    
    # Tier 1 explanation
    print("=== TIER 1 (DEFAULT) ===")
    result = layer.explain(
        score_breakdown=score_breakdown,
        feature_vector=feature_vector,
        tier=ExplanationTier.TIER_1_DEFAULT,
    )
    print(f"Summary: {result['summary']}")
    print(f"Top Components: {result['top_components']}")
    print(f"Traits: {result['trait_alignment']}")
    print()
    
    # Tier 2 explanation
    print("=== TIER 2 (ON-DEMAND) ===")
    result = layer.explain(
        score_breakdown=score_breakdown,
        feature_vector=feature_vector,
        tier=ExplanationTier.TIER_2_ONDEMAND,
    )
    print(f"Weight Analysis: {result.get('weight_analysis', {})}")
    print(f"Sensitivity: {result.get('sensitivity', {})}")
