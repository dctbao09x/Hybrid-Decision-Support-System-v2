from __future__ import annotations

import pytest

from backend.ops.monitoring.costs import CostModelConfig, CostTracker


def _test_config(*, hard_budget_enforcement: bool = True) -> CostModelConfig:
    return CostModelConfig(
        token_input_cost_per_1k_usd=1.0,
        token_output_cost_per_1k_usd=2.0,
        redis_op_cost_usd=0.5,
        queue_op_cost_usd=0.25,
        storage_kb_write_cost_usd=1.0,
        market_crawl_job_cost_usd=10.0,
        daily_budget_usd=100.0,
        monthly_budget_usd=1000.0,
        burn_rate_alert_threshold_1h=10.0,
        burn_rate_alert_threshold_6h=10.0,
        hard_budget_enforcement=hard_budget_enforcement,
    )


def test_cost_tracker_records_components_and_summary() -> None:
    tracker = CostTracker(config=_test_config())

    first = tracker.record_request_cost(
        request_id="r1",
        trace_id="t1",
        endpoint="/api/v1/one-button/run",
        endpoint_version="one_button.response.v1",
        tenant_id="tenant-a",
        model_id="m1",
        model_version="mv1",
        prompt_version="pv1",
        decision_status="SUCCESS",
        explanation_status="success",
        prompt_tokens=1000,
        completion_tokens=500,
        redis_ops=2,
        queue_ops=4,
        storage_bytes=2048,
        market_crawl_jobs=1,
        conversion=True,
    )

    cost = first["record"]["cost"]
    assert cost["token_cost_usd"] == pytest.approx(2.0)
    assert cost["redis_cost_usd"] == pytest.approx(1.0)
    assert cost["queue_cost_usd"] == pytest.approx(1.0)
    assert cost["storage_cost_usd"] == pytest.approx(2.0)
    assert cost["market_crawl_cost_usd"] == pytest.approx(10.0)
    assert cost["total_cost_usd"] == pytest.approx(16.0)

    tracker.record_request_cost(
        request_id="r2",
        trace_id="t2",
        endpoint="/api/v1/one-button/run",
        endpoint_version="one_button.response.v1",
        tenant_id="tenant-a",
        model_id="m1",
        model_version="mv1",
        prompt_version="pv1",
        decision_status="SUCCESS",
        explanation_status="fallback_or_skipped",
        prompt_tokens=0,
        completion_tokens=0,
        redis_ops=0,
        queue_ops=0,
        storage_bytes=0,
        market_crawl_jobs=0,
        conversion=False,
    )

    summary = tracker.get_summary()
    assert summary["total_requests"] == 2
    assert summary["total_cost_usd"] == pytest.approx(16.0)
    assert summary["cost_per_decision_usd"] == pytest.approx(8.0)
    assert summary["cost_per_successful_explanation_usd"] == pytest.approx(16.0)
    assert summary["conversions"] == 1
    assert summary["cost_by_model_usd"]["mv1"] == pytest.approx(16.0)
    assert summary["cost_by_tenant_usd"]["tenant-a"] == pytest.approx(16.0)


def test_budget_guard_blocks_when_budget_exhausted() -> None:
    config = _test_config(hard_budget_enforcement=True)
    config = CostModelConfig(
        **{
            **config.__dict__,
            "daily_budget_usd": 10.0,
            "monthly_budget_usd": 20.0,
        }
    )
    tracker = CostTracker(config=config)

    tracker.record_request_cost(
        request_id="r1",
        trace_id="t1",
        endpoint="/api/v1/one-button/run",
        endpoint_version="one_button.response.v1",
        tenant_id="tenant-a",
        model_id="m1",
        model_version="mv1",
        prompt_version="pv1",
        decision_status="SUCCESS",
        explanation_status="success",
        market_crawl_jobs=2,
    )

    budget = tracker.check_budget_guard(endpoint="/api/v1/one-button/run", tenant_id="tenant-a")
    assert budget["daily_budget_exhausted"] is True
    assert budget["allowed"] is False
    assert budget["reason"] == "budget_exhausted"


def test_budget_guard_allows_when_hard_enforcement_disabled() -> None:
    config = _test_config(hard_budget_enforcement=False)
    config = CostModelConfig(
        **{
            **config.__dict__,
            "daily_budget_usd": 10.0,
            "monthly_budget_usd": 20.0,
        }
    )
    tracker = CostTracker(config=config)

    tracker.record_request_cost(
        request_id="r1",
        trace_id="t1",
        endpoint="/api/v1/one-button/run",
        endpoint_version="one_button.response.v1",
        tenant_id="tenant-a",
        model_id="m1",
        model_version="mv1",
        prompt_version="pv1",
        decision_status="SUCCESS",
        explanation_status="success",
        market_crawl_jobs=2,
    )

    budget = tracker.check_budget_guard(endpoint="/api/v1/one-button/run", tenant_id="tenant-a")
    assert budget["daily_budget_exhausted"] is True
    assert budget["allowed"] is True
    assert budget["reason"] == "within_budget"


def test_dashboard_metrics_contains_unit_economics_fields() -> None:
    tracker = CostTracker(config=_test_config())

    tracker.record_request_cost(
        request_id="r1",
        trace_id="t1",
        endpoint="/api/v1/one-button/run",
        endpoint_version="one_button.response.v1",
        tenant_id="tenant-a",
        model_id="m1",
        model_version="mv1",
        prompt_version="pv1",
        decision_status="SUCCESS",
        explanation_status="success",
        prompt_tokens=100,
        completion_tokens=100,
        conversion=True,
    )

    dashboard = tracker.get_dashboard_metrics()
    assert "cost_per_decision" in dashboard
    assert "cost_per_successful_explanation" in dashboard
    assert "cost_by_model" in dashboard
    assert "cost_by_tenant" in dashboard
    assert "cost_vs_conversion" in dashboard
    assert "conversion_per_usd" in dashboard
    assert dashboard["conversion_per_usd"] > 0
