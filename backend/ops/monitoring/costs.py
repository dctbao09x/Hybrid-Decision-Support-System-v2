"""
Cost observability and unit-economics tracking.

Tracks per-request cost components and aggregates dashboard metrics:
  - cost_per_decision
  - cost_per_successful_explanation
  - cost_by_model
  - cost_by_tenant
  - cost_vs_conversion

Also evaluates burn-rate and budget policy for enforcement.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("ops.monitoring.costs")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class CostModelConfig:
    token_input_cost_per_1k_usd: float = 0.0015
    token_output_cost_per_1k_usd: float = 0.0020
    redis_op_cost_usd: float = 0.0000010
    queue_op_cost_usd: float = 0.0000020
    storage_kb_write_cost_usd: float = 0.0000004
    market_crawl_job_cost_usd: float = 0.0008

    daily_budget_usd: float = 250.0
    monthly_budget_usd: float = 5000.0

    burn_rate_alert_threshold_1h: float = 1.25
    burn_rate_alert_threshold_6h: float = 1.10
    hard_budget_enforcement: bool = True

    @classmethod
    def from_env(cls) -> "CostModelConfig":
        return cls(
            token_input_cost_per_1k_usd=_env_float(
                "COST_TOKEN_INPUT_PER_1K_USD", cls.token_input_cost_per_1k_usd
            ),
            token_output_cost_per_1k_usd=_env_float(
                "COST_TOKEN_OUTPUT_PER_1K_USD", cls.token_output_cost_per_1k_usd
            ),
            redis_op_cost_usd=_env_float("COST_REDIS_OP_USD", cls.redis_op_cost_usd),
            queue_op_cost_usd=_env_float("COST_QUEUE_OP_USD", cls.queue_op_cost_usd),
            storage_kb_write_cost_usd=_env_float(
                "COST_STORAGE_KB_WRITE_USD", cls.storage_kb_write_cost_usd
            ),
            market_crawl_job_cost_usd=_env_float(
                "COST_MARKET_CRAWL_JOB_USD", cls.market_crawl_job_cost_usd
            ),
            daily_budget_usd=_env_float("COST_DAILY_BUDGET_USD", cls.daily_budget_usd),
            monthly_budget_usd=_env_float(
                "COST_MONTHLY_BUDGET_USD", cls.monthly_budget_usd
            ),
            burn_rate_alert_threshold_1h=_env_float(
                "COST_BURN_RATE_ALERT_1H", cls.burn_rate_alert_threshold_1h
            ),
            burn_rate_alert_threshold_6h=_env_float(
                "COST_BURN_RATE_ALERT_6H", cls.burn_rate_alert_threshold_6h
            ),
            hard_budget_enforcement=_env_bool(
                "COST_HARD_BUDGET_ENFORCEMENT", cls.hard_budget_enforcement
            ),
        )


class CostTracker:
    """Central cost tracker used by API and ops dashboards."""

    def __init__(
        self,
        *,
        metrics: Optional[Any] = None,
        alerts: Optional[Any] = None,
        anomaly: Optional[Any] = None,
        config: Optional[CostModelConfig] = None,
        history_size: int = 5000,
    ) -> None:
        self._metrics = metrics
        self._alerts = alerts
        self._anomaly = anomaly
        self._config = config or CostModelConfig.from_env()

        self._records: Deque[Dict[str, Any]] = deque(maxlen=max(200, history_size))
        self._recent_anomalies: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._lock = threading.Lock()

    def record_request_cost(
        self,
        *,
        request_id: str,
        trace_id: str,
        endpoint: str,
        endpoint_version: str,
        tenant_id: Optional[str],
        model_id: Optional[str],
        model_version: Optional[str],
        prompt_version: Optional[str],
        decision_status: str,
        explanation_status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        redis_ops: int = 0,
        queue_ops: int = 0,
        storage_bytes: int = 0,
        market_crawl_jobs: int = 0,
        conversion: bool = False,
    ) -> Dict[str, Any]:
        now = time.time()

        in_tokens = max(int(prompt_tokens), 0)
        out_tokens = max(int(completion_tokens), 0)
        redis_count = max(int(redis_ops), 0)
        queue_count = max(int(queue_ops), 0)
        storage_kb = max(float(storage_bytes), 0.0) / 1024.0
        crawl_jobs = max(int(market_crawl_jobs), 0)

        token_cost = (
            (in_tokens / 1000.0) * self._config.token_input_cost_per_1k_usd
            + (out_tokens / 1000.0) * self._config.token_output_cost_per_1k_usd
        )
        redis_cost = redis_count * self._config.redis_op_cost_usd
        queue_cost = queue_count * self._config.queue_op_cost_usd
        storage_cost = storage_kb * self._config.storage_kb_write_cost_usd
        market_crawl_cost = crawl_jobs * self._config.market_crawl_job_cost_usd
        total_cost = token_cost + redis_cost + queue_cost + storage_cost + market_crawl_cost

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epoch": now,
            "request_id": request_id,
            "trace_id": trace_id,
            "endpoint": endpoint,
            "endpoint_version": endpoint_version,
            "tenant_id": tenant_id or "anonymous",
            "model_id": model_id or "unknown",
            "model_version": model_version or "unknown",
            "prompt_version": prompt_version or "unknown",
            "decision_status": str(decision_status or "unknown"),
            "explanation_status": str(explanation_status or "unknown"),
            "conversion": bool(conversion),
            "usage": {
                "prompt_tokens": in_tokens,
                "completion_tokens": out_tokens,
                "redis_ops": redis_count,
                "queue_ops": queue_count,
                "storage_bytes": max(int(storage_bytes), 0),
                "market_crawl_jobs": crawl_jobs,
            },
            "cost": {
                "token_cost_usd": round(token_cost, 10),
                "redis_cost_usd": round(redis_cost, 10),
                "queue_cost_usd": round(queue_cost, 10),
                "storage_cost_usd": round(storage_cost, 10),
                "market_crawl_cost_usd": round(market_crawl_cost, 10),
                "total_cost_usd": round(total_cost, 10),
            },
        }

        with self._lock:
            self._records.append(record)
            summary = self._build_summary_locked(now)

        self._emit_metrics(record, summary)
        self._evaluate_anomaly_and_alerts(record, summary)

        return {
            "record": record,
            "unit_economics": {
                "cost_per_decision_usd": summary["cost_per_decision_usd"],
                "cost_per_successful_explanation_usd": summary[
                    "cost_per_successful_explanation_usd"
                ],
                "cost_vs_conversion": summary["cost_vs_conversion"],
                "conversion_per_usd": summary["conversion_per_usd"],
            },
            "budget": {
                "daily_spend_usd": summary["daily_spend_usd"],
                "monthly_spend_usd": summary["monthly_spend_usd"],
                "daily_budget_utilization": summary["daily_budget_utilization"],
                "monthly_budget_utilization": summary["monthly_budget_utilization"],
                "daily_budget_exhausted": summary["daily_budget_exhausted"],
                "monthly_budget_exhausted": summary["monthly_budget_exhausted"],
            },
        }

    def check_budget_guard(
        self,
        *,
        endpoint: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        summary = self.get_summary()
        exhausted = bool(
            summary["daily_budget_exhausted"] or summary["monthly_budget_exhausted"]
        )
        hard = bool(self._config.hard_budget_enforcement)
        allowed = not (hard and exhausted)

        return {
            "allowed": allowed,
            "hard_budget_enforcement": hard,
            "endpoint": endpoint,
            "tenant_id": tenant_id or "anonymous",
            "daily_spend_usd": summary["daily_spend_usd"],
            "monthly_spend_usd": summary["monthly_spend_usd"],
            "daily_budget_usd": self._config.daily_budget_usd,
            "monthly_budget_usd": self._config.monthly_budget_usd,
            "daily_budget_exhausted": summary["daily_budget_exhausted"],
            "monthly_budget_exhausted": summary["monthly_budget_exhausted"],
            "reason": (
                "budget_exhausted"
                if (hard and exhausted)
                else "within_budget"
            ),
        }

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_summary_locked(time.time())

    def get_budget_status(self) -> Dict[str, Any]:
        summary = self.get_summary()
        return {
            "daily_spend_usd": summary["daily_spend_usd"],
            "monthly_spend_usd": summary["monthly_spend_usd"],
            "daily_budget_usd": self._config.daily_budget_usd,
            "monthly_budget_usd": self._config.monthly_budget_usd,
            "daily_budget_utilization": summary["daily_budget_utilization"],
            "monthly_budget_utilization": summary["monthly_budget_utilization"],
            "daily_budget_exhausted": summary["daily_budget_exhausted"],
            "monthly_budget_exhausted": summary["monthly_budget_exhausted"],
            "burn_rate_1h": summary["burn_rate_1h"],
            "burn_rate_6h": summary["burn_rate_6h"],
            "hard_budget_enforcement": self._config.hard_budget_enforcement,
        }

    def get_recent_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            count = max(int(limit), 1)
            records = list(self._records)[-count:]
        records.reverse()
        return records

    def get_dashboard_metrics(self) -> Dict[str, Any]:
        summary = self.get_summary()
        return {
            "cost_per_decision": summary["cost_per_decision_usd"],
            "cost_per_successful_explanation": summary[
                "cost_per_successful_explanation_usd"
            ],
            "cost_by_model": summary["cost_by_model_usd"],
            "cost_by_tenant": summary["cost_by_tenant_usd"],
            "cost_vs_conversion": summary["cost_vs_conversion"],
            "conversion_per_usd": summary["conversion_per_usd"],
            "burn_rate_1h": summary["burn_rate_1h"],
            "burn_rate_6h": summary["burn_rate_6h"],
            "recent_anomalies": list(self._recent_anomalies),
        }

    def _build_summary_locked(self, now: float) -> Dict[str, Any]:
        total_cost = 0.0
        successful_explanations = 0
        conversions = 0
        by_model = defaultdict(float)
        by_tenant = defaultdict(float)

        for item in self._records:
            cost = float(item.get("cost", {}).get("total_cost_usd", 0.0) or 0.0)
            total_cost += cost

            if item.get("explanation_status") == "success":
                successful_explanations += 1
            if bool(item.get("conversion", False)):
                conversions += 1

            model_key = str(item.get("model_version") or item.get("model_id") or "unknown")
            tenant_key = str(item.get("tenant_id") or "anonymous")
            by_model[model_key] += cost
            by_tenant[tenant_key] += cost

        total_requests = len(self._records)
        cost_per_decision = total_cost / total_requests if total_requests else 0.0
        cost_per_successful_explanation = (
            total_cost / successful_explanations if successful_explanations else 0.0
        )
        cost_per_conversion = total_cost / conversions if conversions else 0.0
        conversion_per_usd = conversions / total_cost if total_cost > 0 else 0.0

        day_start = self._day_start_epoch(now)
        month_start = self._month_start_epoch(now)

        daily_spend = sum(
            float(item.get("cost", {}).get("total_cost_usd", 0.0) or 0.0)
            for item in self._records
            if float(item.get("epoch", 0.0) or 0.0) >= day_start
        )
        monthly_spend = sum(
            float(item.get("cost", {}).get("total_cost_usd", 0.0) or 0.0)
            for item in self._records
            if float(item.get("epoch", 0.0) or 0.0) >= month_start
        )

        spend_1h = self._spend_since_locked(now, window_seconds=3600)
        spend_6h = self._spend_since_locked(now, window_seconds=6 * 3600)

        expected_1h = self._config.daily_budget_usd / 24.0 if self._config.daily_budget_usd > 0 else 0.0
        expected_6h = (self._config.daily_budget_usd * 6.0 / 24.0) if self._config.daily_budget_usd > 0 else 0.0

        burn_rate_1h = spend_1h / expected_1h if expected_1h > 0 else 0.0
        burn_rate_6h = spend_6h / expected_6h if expected_6h > 0 else 0.0

        daily_util = daily_spend / self._config.daily_budget_usd if self._config.daily_budget_usd > 0 else 0.0
        monthly_util = monthly_spend / self._config.monthly_budget_usd if self._config.monthly_budget_usd > 0 else 0.0

        return {
            "total_requests": total_requests,
            "total_cost_usd": round(total_cost, 8),
            "cost_per_decision_usd": round(cost_per_decision, 8),
            "cost_per_successful_explanation_usd": round(
                cost_per_successful_explanation, 8
            ),
            "cost_vs_conversion": round(cost_per_conversion, 8),
            "conversion_per_usd": round(conversion_per_usd, 8),
            "successful_explanations": successful_explanations,
            "conversions": conversions,
            "cost_by_model_usd": {
                k: round(v, 8) for k, v in sorted(by_model.items(), key=lambda kv: kv[0])
            },
            "cost_by_tenant_usd": {
                k: round(v, 8) for k, v in sorted(by_tenant.items(), key=lambda kv: kv[0])
            },
            "daily_spend_usd": round(daily_spend, 8),
            "monthly_spend_usd": round(monthly_spend, 8),
            "daily_budget_utilization": round(daily_util, 8),
            "monthly_budget_utilization": round(monthly_util, 8),
            "daily_budget_exhausted": bool(
                self._config.daily_budget_usd > 0 and daily_spend >= self._config.daily_budget_usd
            ),
            "monthly_budget_exhausted": bool(
                self._config.monthly_budget_usd > 0 and monthly_spend >= self._config.monthly_budget_usd
            ),
            "burn_rate_1h": round(burn_rate_1h, 8),
            "burn_rate_6h": round(burn_rate_6h, 8),
        }

    def _spend_since_locked(self, now: float, *, window_seconds: int) -> float:
        cutoff = now - float(window_seconds)
        return sum(
            float(item.get("cost", {}).get("total_cost_usd", 0.0) or 0.0)
            for item in self._records
            if float(item.get("epoch", 0.0) or 0.0) >= cutoff
        )

    @staticmethod
    def _day_start_epoch(now: float) -> float:
        dt_now = datetime.fromtimestamp(now, tz=timezone.utc)
        day_start = datetime(dt_now.year, dt_now.month, dt_now.day, tzinfo=timezone.utc)
        return day_start.timestamp()

    @staticmethod
    def _month_start_epoch(now: float) -> float:
        dt_now = datetime.fromtimestamp(now, tz=timezone.utc)
        month_start = datetime(dt_now.year, dt_now.month, 1, tzinfo=timezone.utc)
        return month_start.timestamp()

    def _emit_metrics(self, record: Dict[str, Any], summary: Dict[str, Any]) -> None:
        if self._metrics is None:
            return

        try:
            total = float(record["cost"]["total_cost_usd"])
            self._metrics.inc("cost_records_total")
            self._metrics.inc("cost_total_usd", value=total)
            self._metrics.inc(
                "cost_component_usd_total",
                value=float(record["cost"]["token_cost_usd"]),
                labels={"component": "token"},
            )
            self._metrics.inc(
                "cost_component_usd_total",
                value=float(record["cost"]["redis_cost_usd"]),
                labels={"component": "redis"},
            )
            self._metrics.inc(
                "cost_component_usd_total",
                value=float(record["cost"]["queue_cost_usd"]),
                labels={"component": "queue"},
            )
            self._metrics.inc(
                "cost_component_usd_total",
                value=float(record["cost"]["storage_cost_usd"]),
                labels={"component": "storage"},
            )
            self._metrics.inc(
                "cost_component_usd_total",
                value=float(record["cost"]["market_crawl_cost_usd"]),
                labels={"component": "market_crawl"},
            )

            self._metrics.inc(
                "cost_by_model_usd",
                value=total,
                labels={"model": str(record.get("model_version") or "unknown")},
            )
            self._metrics.inc(
                "cost_by_tenant_usd",
                value=total,
                labels={"tenant": str(record.get("tenant_id") or "anonymous")},
            )

            self._metrics.set_gauge("cost_last_request_usd", total)
            self._metrics.set_gauge(
                "cost_per_decision", float(summary["cost_per_decision_usd"])
            )
            self._metrics.set_gauge(
                "cost_per_successful_explanation",
                float(summary["cost_per_successful_explanation_usd"]),
            )
            self._metrics.set_gauge(
                "cost_vs_conversion", float(summary["cost_vs_conversion"])
            )
            self._metrics.set_gauge(
                "cost_conversion_per_usd", float(summary["conversion_per_usd"])
            )
            self._metrics.set_gauge("cost_burn_rate_1h", float(summary["burn_rate_1h"]))
            self._metrics.set_gauge("cost_burn_rate_6h", float(summary["burn_rate_6h"]))
            self._metrics.set_gauge(
                "cost_budget_daily_utilization",
                float(summary["daily_budget_utilization"]),
            )
            self._metrics.set_gauge(
                "cost_budget_monthly_utilization",
                float(summary["monthly_budget_utilization"]),
            )
        except Exception:
            logger.debug("cost metric emission failed", exc_info=True)

    def _evaluate_anomaly_and_alerts(
        self,
        record: Dict[str, Any],
        summary: Dict[str, Any],
    ) -> None:
        total = float(record.get("cost", {}).get("total_cost_usd", 0.0) or 0.0)

        anomaly_event = None
        if self._anomaly is not None and hasattr(self._anomaly, "record"):
            try:
                anomaly_event = self._anomaly.record("cost_per_request_usd", total)
            except Exception:
                logger.debug("cost anomaly detector update failed", exc_info=True)

        if anomaly_event and str(anomaly_event.get("direction", "")) == "high":
            self._recent_anomalies.append(anomaly_event)
            self._schedule_alert(
                title="Cost anomaly spike detected",
                message=(
                    "Cost per request is anomalous: "
                    f"value={anomaly_event.get('value')} z={anomaly_event.get('z_score')}"
                ),
                severity="critical",
                context={
                    "metric": anomaly_event.get("metric"),
                    "value": anomaly_event.get("value"),
                    "z_score": anomaly_event.get("z_score"),
                    "pct_change": anomaly_event.get("pct_change"),
                },
            )

        if float(summary.get("burn_rate_1h", 0.0)) >= float(
            self._config.burn_rate_alert_threshold_1h
        ):
            self._schedule_alert(
                title="Cost burn-rate threshold breached (1h)",
                message=(
                    f"1h burn-rate={summary.get('burn_rate_1h')} exceeds "
                    f"threshold={self._config.burn_rate_alert_threshold_1h}"
                ),
                severity="critical",
                context={
                    "burn_rate_1h": summary.get("burn_rate_1h"),
                    "daily_spend_usd": summary.get("daily_spend_usd"),
                    "daily_budget_usd": self._config.daily_budget_usd,
                },
            )

        if float(summary.get("burn_rate_6h", 0.0)) >= float(
            self._config.burn_rate_alert_threshold_6h
        ):
            self._schedule_alert(
                title="Cost burn-rate threshold breached (6h)",
                message=(
                    f"6h burn-rate={summary.get('burn_rate_6h')} exceeds "
                    f"threshold={self._config.burn_rate_alert_threshold_6h}"
                ),
                severity="warning",
                context={
                    "burn_rate_6h": summary.get("burn_rate_6h"),
                    "monthly_spend_usd": summary.get("monthly_spend_usd"),
                    "monthly_budget_usd": self._config.monthly_budget_usd,
                },
            )

        if bool(summary.get("daily_budget_exhausted", False)):
            self._schedule_alert(
                title="Daily cost budget exhausted",
                message=(
                    f"Daily spend {summary.get('daily_spend_usd')} exceeded "
                    f"budget {self._config.daily_budget_usd}"
                ),
                severity="fatal",
                context={
                    "daily_spend_usd": summary.get("daily_spend_usd"),
                    "daily_budget_usd": self._config.daily_budget_usd,
                    "hard_budget_enforcement": self._config.hard_budget_enforcement,
                },
            )

        if bool(summary.get("monthly_budget_exhausted", False)):
            self._schedule_alert(
                title="Monthly cost budget exhausted",
                message=(
                    f"Monthly spend {summary.get('monthly_spend_usd')} exceeded "
                    f"budget {self._config.monthly_budget_usd}"
                ),
                severity="fatal",
                context={
                    "monthly_spend_usd": summary.get("monthly_spend_usd"),
                    "monthly_budget_usd": self._config.monthly_budget_usd,
                    "hard_budget_enforcement": self._config.hard_budget_enforcement,
                },
            )

    def _schedule_alert(
        self,
        *,
        title: str,
        message: str,
        severity: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._alerts is None or not hasattr(self._alerts, "fire"):
            return

        async def _emit() -> None:
            try:
                await self._alerts.fire(
                    title=title,
                    message=message,
                    severity=severity,
                    source="cost",
                    context=context or {},
                )
            except Exception:
                logger.debug("cost alert delivery failed", exc_info=True)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit())
        except RuntimeError:
            logger.debug("no running loop available for async alert delivery")
