from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
from backend.scoring.config import ScoringConfig
from backend.scoring.engine import RankingEngine, RankingContext
from backend.scoring.models import CareerData, UserProfile

logger = logging.getLogger(__name__)


@dataclass
class ShadowScoreDelta:
    avg_score_diff: float
    max_score_diff: float
    top_label_match: bool
    match: bool
    component_max_diff: float = 0.0
    component_drift: bool = False
    component_diffs: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_score_diff": round(self.avg_score_diff, 6),
            "max_score_diff": round(self.max_score_diff, 6),
            "top_label_match": self.top_label_match,
            "match": self.match,
            "component_max_diff": round(self.component_max_diff, 6),
            "component_drift": self.component_drift,
            "component_diffs": self.component_diffs or {},
        }


class ShadowScoringRunner:
    """Run scoring in shadow mode and compare results."""

    def __init__(
        self,
        engine: Optional[RankingEngine] = None,
        dispatcher: Optional[ShadowDispatcher] = None,
        max_score_diff: float = 0.15,
        component_max_diff: float = 0.2,
        top_n: int = 5,
    ) -> None:
        self.engine = engine or RankingEngine()
        self.dispatcher = dispatcher or ShadowDispatcher()
        self.max_score_diff = max_score_diff
        self.component_max_diff = component_max_diff
        self.top_n = top_n

        self.dispatcher.set_comparison_function(self._compare_results)

    async def rank_with_shadow(
        self,
        user: UserProfile,
        careers: List[CareerData],
        *,
        shadow_version: Optional[str] = None,
        shadow_config: Optional[ScoringConfig] = None,
        strategy_name: Optional[str] = None,
        trace_id: Optional[str] = None,
        request_sample: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run prod and shadow scoring in parallel and compare results."""
        ctx = RankingContext()
        prod_results = self.engine.rank_dto(
            user=user,
            careers=careers,
            strategy_name=strategy_name,
            context=ctx,
        )

        if shadow_config is None:
            if shadow_version:
                shadow_config = ScoringConfig.from_trained_weights(
                    version=shadow_version
                )
            else:
                shadow_config = ScoringConfig.from_trained_weights()

        shadow_results = self.engine.rank_dto(
            user=user,
            careers=careers,
            config_override=shadow_config,
            strategy_name=strategy_name,
            context=ctx,
        )

        comparison = await self.dispatcher.dispatch(
            trace_id=trace_id or ctx.request_id,
            request=request_sample,
            prod_model_id=None,
            shadow_model_id=shadow_version or "active",
            prod_result=self._reduce_results(prod_results),
            shadow_result=self._reduce_results(shadow_results),
        )

        delta = self._compare_results(prod_results, shadow_results).get("delta", {})
        if not delta.get("match", True):
            logger.warning("Shadow scoring drift detected: %s", delta)

        if delta.get("component_drift"):
            logger.warning("Shadow component drift detected: %s", delta.get("component_diffs"))

        return {
            "prod_results": prod_results,
            "shadow_results": shadow_results,
            "comparison": comparison.to_dict(),
            "delta": delta,
        }

    def _reduce_results(self, results: List[Any]) -> Dict[str, Any]:
        top = results[: self.top_n]
        if not top:
            return {"score": 0.0, "label": None}
        return {
            "score": float(top[0].total_score),
            "label": top[0].career_id,
        }

    def _compare_results(self, prod_results: Any, shadow_results: Any) -> Dict[str, Any]:
        prod_list = list(prod_results) if isinstance(prod_results, list) else []
        shadow_list = list(shadow_results) if isinstance(shadow_results, list) else []

        if not prod_list or not shadow_list:
            return {"delta": {"error": "empty_results"}, "match": False}

        prod_top = prod_list[0]
        shadow_top = shadow_list[0]

        prod_scores = {r.career_id: float(r.total_score) for r in prod_list[: self.top_n]}
        shadow_scores = {r.career_id: float(r.total_score) for r in shadow_list[: self.top_n]}

        diffs = []
        for career_id, prod_score in prod_scores.items():
            shadow_score = shadow_scores.get(career_id)
            if shadow_score is None:
                continue
            diffs.append(abs(shadow_score - prod_score))

        avg_diff = sum(diffs) / len(diffs) if diffs else 0.0
        max_diff = max(diffs) if diffs else 0.0

        component_diffs: Dict[str, float] = {}
        component_max_diff = 0.0
        for career_id, prod_score in prod_scores.items():
            shadow_score = shadow_scores.get(career_id)
            if shadow_score is None:
                continue

            prod_item = next((r for r in prod_list if r.career_id == career_id), None)
            shadow_item = next((r for r in shadow_list if r.career_id == career_id), None)

            if not prod_item or not shadow_item:
                continue

            prod_components = getattr(prod_item, "components", {}) or {}
            shadow_components = getattr(shadow_item, "components", {}) or {}

            for key, prod_val in prod_components.items():
                shadow_val = shadow_components.get(key)
                if shadow_val is None:
                    continue
                diff = abs(float(prod_val) - float(shadow_val))
                component_diffs[key] = max(component_diffs.get(key, 0.0), diff)
                component_max_diff = max(component_max_diff, diff)

        top_label_match = prod_top.career_id == shadow_top.career_id
        component_drift = component_max_diff > self.component_max_diff if component_diffs else False
        match = max_diff <= self.max_score_diff and top_label_match and not component_drift

        delta = ShadowScoreDelta(
            avg_score_diff=avg_diff,
            max_score_diff=max_diff,
            top_label_match=top_label_match,
            match=match,
            component_max_diff=component_max_diff,
            component_drift=component_drift,
            component_diffs=component_diffs,
        )

        return {"delta": delta.to_dict(), "match": match}
