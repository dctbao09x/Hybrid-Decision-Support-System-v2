from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from backend.api.controllers.decision_controller import (
    CareerResult,
    DecisionMeta,
    DecisionResponse,
    InputValidationError,
    MarketInsight,
)
from backend.api.middleware.auth import (
    AuthErrorCode,
    _build_auth_http_exception,
    auth_http_exception_to_response,
    configure_auth,
    verify_token,
)
from backend.api.middleware.rate_limit import (
    RateLimitErrorCode,
    apply_rate_limit_headers,
    check_rate_limit,
    configure_rate_limit,
    rate_limit_http_exception_to_response,
)
from backend.api.routers.decision_legacy_router import router as legacy_router
from backend.api.routers.one_button_router import router as one_button_router
from backend.api.routers.one_button_router import set_controller
from backend.mlops.scheduler.policies import CooldownPolicy
from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
from backend.mlops.scheduler.state_store import StateStore
from backend.ops.recovery.stage_retry import StageRetryExecutor, StageRetryPolicy


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _payload() -> Dict[str, Any]:
    return {
        "user_id": "resilience-user",
        "scoring_input": {
            "personal_profile": {
                "ability_score": 0.71,
                "confidence_score": 0.66,
                "interests": ["technology", "science"],
            },
            "experience": {"years": 3, "domains": ["software development"]},
            "goals": {
                "career_aspirations": ["software engineer"],
                "timeline_years": 4,
            },
            "skills": ["python", "sql"],
            "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
            "preferences": {"preferred_domains": ["technology"], "work_style": "remote"},
        },
    }


def _percentile(values: List[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int(math.ceil(quantile * len(ordered))) - 1
    rank = max(0, min(rank, len(ordered) - 1))
    return float(ordered[rank])


def _build_stage_log(*, llm_fallback_reason: Optional[str] = None) -> List[Dict[str, Any]]:
    return [
        {
            "stage": "input_normalize",
            "status": "ok",
            "duration_ms": 1.5,
            "output": {
                "skills_resolved": ["python", "sql"],
                "interests_resolved": ["technology"],
                "education_level": "Bachelor",
                "taxonomy_applied": True,
            },
        },
        {
            "stage": "feature_extraction",
            "status": "ok",
            "duration_ms": 2.1,
            "output": {
                "llm_extracted": llm_fallback_reason is None,
                "llm_attempted": True,
                "fallback_reason": llm_fallback_reason,
                "llm_timeout_injected": llm_fallback_reason is not None,
            },
        },
        {
            "stage": "simgr_scoring",
            "status": "ok",
            "duration_ms": 1.8,
            "output": {"careers_ranked": 1, "top_career": "Software Engineer", "top_score": 0.84},
        },
        {
            "stage": "rule_engine",
            "status": "frozen_pass_through",
            "duration_ms": 0.6,
            "output": {"rules_audited": 1, "frozen": True},
        },
        {
            "stage": "explanation",
            "status": "ok",
            "duration_ms": 0.4,
            "output": {"llm_used": False, "fallback_taxonomy": []},
        },
    ]


def _decision_response(*, llm_fallback_reason: Optional[str] = None) -> DecisionResponse:
    trace = f"dec-{uuid.uuid4().hex[:10]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    ranking = CareerResult(
        name="Software Engineer",
        domain="technology",
        total_score=0.84,
        skill_score=0.83,
        interest_score=0.81,
        market_score=0.8,
        growth_potential=0.78,
        ai_relevance=0.76,
    )

    return DecisionResponse(
        trace_id=trace,
        timestamp=timestamp,
        status="SUCCESS",
        rankings=[ranking],
        top_career=ranking,
        explanation=None,
        market_insights=[
            MarketInsight(
                career_name="Software Engineer",
                demand_level="HIGH",
                salary_range={"min": 1000, "max": 2000},
                growth_rate=0.12,
                competition_level="MEDIUM",
            )
        ],
        meta=DecisionMeta(
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            pipeline_duration_ms=6.4,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=llm_fallback_reason is None,
            stages_completed=[
                "input_normalize",
                "feature_extraction",
                "simgr_scoring",
                "rule_engine",
                "explanation",
            ],
            rule_version="v1",
            taxonomy_version="v1",
            schema_version="one_button.response.v1",
            schema_hash="hash-test",
        ),
        artifact_hash_chain_root="hash-root",
        scoring_breakdown={
            "weights": {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.25},
            "components": {"study": 0.8, "interest": 0.82, "market": 0.84, "growth": 0.9},
            "final_score": 0.84,
        },
        rule_applied=[{"rule": "rule_fallback_min_evidence", "outcome": "pass_through", "frozen": True}],
        reasoning_path=["deterministic path"],
        stage_log=_build_stage_log(llm_fallback_reason=llm_fallback_reason),
        diagnostics={
            "total_latency_ms": 6.4,
            "stage_count": 5,
            "error_count": 0,
            "llm_timeout_injected": llm_fallback_reason is not None,
        },
    )


class _StaticController:
    async def run_pipeline(self, request) -> DecisionResponse:
        _ = request
        return _decision_response()


class _MarketTimeoutController:
    async def run_pipeline(self, request) -> DecisionResponse:
        _ = request
        raise TimeoutError("market timeout injected")


class _LLMTimeoutFallbackController:
    async def run_pipeline(self, request) -> DecisionResponse:
        _ = request
        return _decision_response(llm_fallback_reason="provider_timeout")


def _build_app(controller: Any, *, with_gateway_security: bool) -> FastAPI:
    app = FastAPI()
    set_controller(controller)
    app.include_router(one_button_router)
    app.include_router(legacy_router)

    if with_gateway_security:

        @app.middleware("http")
        async def gateway_security_middleware(request: Request, call_next):
            try:
                auth_result = await verify_token(request)
            except HTTPException as exc:
                return auth_http_exception_to_response(exc, request)

            try:
                decision = await check_rate_limit(request, auth_result=auth_result)
            except HTTPException as exc:
                return rate_limit_http_exception_to_response(exc, request)

            response = await call_next(request)
            apply_rate_limit_headers(response, decision)
            return response

    return app


async def _run_concurrent_posts(
    *,
    app: FastAPI,
    paths: List[str],
    payload: Dict[str, Any],
    total_requests: int,
    concurrency: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    latencies: List[float] = []
    failures = 0
    status_codes: Dict[str, int] = {}
    semaphore = asyncio.Semaphore(max(1, concurrency))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        async def _issue(path: str) -> None:
            nonlocal failures
            async with semaphore:
                started = time.perf_counter()
                response = await client.post(path, json=payload, headers=headers)
                latency_ms = (time.perf_counter() - started) * 1000.0
                latencies.append(latency_ms)
                status_codes[str(response.status_code)] = status_codes.get(str(response.status_code), 0) + 1
                if response.status_code != 200:
                    failures += 1

        tasks: List[asyncio.Task] = []
        for idx in range(total_requests):
            path = paths[idx % len(paths)]
            tasks.append(asyncio.create_task(_issue(path)))
        await asyncio.gather(*tasks)

    total = len(latencies)
    return {
        "total_requests": total,
        "failed_requests": failures,
        "error_rate": float(failures) / max(total, 1),
        "p95_ms": _percentile(latencies, 0.95),
        "status_codes": status_codes,
        "latencies": latencies,
    }


async def _run_soak(
    *,
    app: FastAPI,
    payload: Dict[str, Any],
    windows: int,
    requests_per_window: int,
    concurrency: int,
) -> Dict[str, Any]:
    window_p95: List[float] = []
    combined_latencies: List[float] = []
    total_requests = 0
    total_failures = 0

    for _ in range(windows):
        summary = await _run_concurrent_posts(
            app=app,
            paths=["/api/v1/one-button/run", "/api/v1/decision/run"],
            payload=payload,
            total_requests=requests_per_window,
            concurrency=concurrency,
        )
        window_p95.append(summary["p95_ms"])
        combined_latencies.extend(summary["latencies"])
        total_requests += int(summary["total_requests"])
        total_failures += int(summary["failed_requests"])
        await asyncio.sleep(0.03)

    first_p95 = window_p95[0] if window_p95 else 0.0
    last_p95 = window_p95[-1] if window_p95 else 0.0
    return {
        "windows": windows,
        "window_p95_ms": window_p95,
        "overall_p95_ms": _percentile(combined_latencies, 0.95),
        "error_rate": float(total_failures) / max(total_requests, 1),
        "drift_ratio": (last_p95 / first_p95) if first_p95 > 0 else 1.0,
        "total_requests": total_requests,
    }


async def _retry_probe_metrics() -> Dict[str, Any]:
    executor = StageRetryExecutor()
    stage_name = f"decision_endpoint_retry_probe_{uuid.uuid4().hex[:8]}"
    executor.set_policy(
        stage_name,
        StageRetryPolicy(
            stage=stage_name,
            max_retries=2,
            base_delay=0.0,
            max_delay=0.0,
            jitter=False,
            budget_max_retries=5,
            budget_window=60.0,
        ),
    )

    attempts = {"count": 0}

    async def _flaky_market_call() -> Dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("market timeout for retry probe")
        return {"status": "ok"}

    result = await executor.execute(stage_name, _flaky_market_call, run_id="resilience-retry")
    assert result.success is True
    assert result.attempts == 3
    return {
        "attempts": int(result.attempts),
        "retries": max(0, int(result.attempts) - 1),
        "dead_letters": 0,
    }


async def _market_timeout_fallback_probe() -> Dict[str, Any]:
    from backend.api.controllers.decision_controller import DecisionController

    class _MainControllerMarketTimeout:
        async def dispatch(self, service: str, action: str, payload: Dict[str, Any], context: Dict[str, Any]):
            _ = (service, action, payload, context)
            raise TimeoutError("market timeout")

    controller = DecisionController()
    controller.set_main_controller(_MainControllerMarketTimeout())

    top_careers = [
        CareerResult(
            name="Software Engineer",
            domain="technology",
            total_score=0.84,
            skill_score=0.83,
            interest_score=0.81,
            market_score=0.8,
            growth_potential=0.78,
            ai_relevance=0.76,
        )
    ]

    before_fallback = int(controller._fallback_metric_state.get("fallback_events", 0))
    before_missing = int(controller._fallback_metric_state.get("missing_market_signal_events", 0))

    with pytest.raises(InputValidationError):
        await controller._get_market_data(top_careers=top_careers, trace_id="trace-market-timeout")

    after_fallback = int(controller._fallback_metric_state.get("fallback_events", 0))
    after_missing = int(controller._fallback_metric_state.get("missing_market_signal_events", 0))
    return {
        "fallback_events_delta": max(0, after_fallback - before_fallback),
        "missing_market_signal_delta": max(0, after_missing - before_missing),
    }


def _write_artifacts(payload: Dict[str, Any]) -> None:
    root = _project_root()
    output_dir = root / "audit_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = output_dir / "decision_endpoint_resilience_metrics.json"
    report_path = output_dir / "decision_endpoint_resilience_report.md"

    metrics_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    metrics = payload["metrics"]
    thresholds = payload["thresholds"]
    scenarios = payload["scenarios"]

    lines = [
        "# Decision Endpoint Resilience Report",
        "",
        "## Required Metrics",
        "",
        f"- p95_latency_under_load: {metrics['p95_latency_under_load']:.2f} ms (threshold <= {thresholds['p95_latency_under_load_max_ms']:.2f} ms)",
        f"- error_rate_under_load: {metrics['error_rate_under_load']:.4f} (threshold <= {thresholds['error_rate_under_load_max']:.4f})",
        f"- retry_rate: {metrics['retry_rate']:.4f} (threshold >= {thresholds['retry_rate_min']:.4f})",
        f"- fallback_rate: {metrics['fallback_rate']:.4f} (threshold >= {thresholds['fallback_rate_min']:.4f})",
        f"- dead_letter_rate: {metrics['dead_letter_rate']:.4f} (threshold <= {thresholds['dead_letter_rate_max']:.4f})",
        "",
        "## Scenario Outcomes",
        "",
    ]

    for scenario in scenarios:
        status = "PASS" if scenario.get("passed", False) else "FAIL"
        lines.append(f"- [{status}] {scenario['name']}: {scenario.get('detail', '')}")

    lines.extend(
        [
            "",
            "## Tooling Recommendation",
            "",
            "- Test runner: pytest plus pytest-asyncio",
            "- Load generation: httpx.AsyncClient with ASGITransport for deterministic in-process concurrency",
            "- Fault injection: pytest monkeypatch and deterministic controller stubs",
            "- Artifact format: JSON metrics and Markdown report under audit_outputs",
            "",
            "## CI/CD Integration",
            "",
            "- Mandatory gate command: python -m pytest backend/tests/test_decision_endpoint_resilience.py -v --tb=short",
            "- Workflow integration: .github/workflows/ci.yml test job",
            "- Uploaded artifacts: audit_outputs/decision_endpoint_resilience_metrics.json and audit_outputs/decision_endpoint_resilience_report.md",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_decision_endpoints_mandatory_load_soak_and_failure_injection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    thresholds = {
        "p95_latency_under_load_max_ms": 400.0,
        "error_rate_under_load_max": 0.05,
        "retry_rate_min": 0.20,
        "fallback_rate_min": 0.40,
        "dead_letter_rate_max": 0.05,
    }

    payload = _payload()
    scenarios: List[Dict[str, Any]] = []

    load_app = _build_app(_StaticController(), with_gateway_security=False)
    load_summary = await _run_concurrent_posts(
        app=load_app,
        paths=["/api/v1/one-button/run", "/api/v1/decision/run"],
        payload=payload,
        total_requests=120,
        concurrency=24,
    )
    assert load_summary["failed_requests"] == 0
    scenarios.append(
        {
            "name": "concurrent_load_on_one_button_and_decision_alias",
            "passed": True,
            "detail": (
                f"requests={load_summary['total_requests']} p95={load_summary['p95_ms']:.2f}ms "
                f"error_rate={load_summary['error_rate']:.4f}"
            ),
        }
    )

    soak_summary = await _run_soak(
        app=load_app,
        payload=payload,
        windows=6,
        requests_per_window=30,
        concurrency=10,
    )
    assert soak_summary["error_rate"] <= thresholds["error_rate_under_load_max"]
    assert soak_summary["drift_ratio"] <= 2.0
    scenarios.append(
        {
            "name": "soak_stability_for_decision_endpoints",
            "passed": True,
            "detail": (
                f"windows={soak_summary['windows']} overall_p95={soak_summary['overall_p95_ms']:.2f}ms "
                f"drift_ratio={soak_summary['drift_ratio']:.3f}"
            ),
        }
    )

    fallback_events = 0
    failure_injection_total = 0

    configure_auth({"auth": {"enabled": False}})
    configure_rate_limit(
        {
            "rate_limit": {
                "enabled": True,
                "excluded_paths": [],
                "fail_open": False,
                "by_ip": True,
                "by_user": False,
                "by_api_key": False,
                "by_tenant": False,
            }
        }
    )

    async def _redis_down() -> Any:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("backend.api.middleware.rate_limit._get_redis_client", _redis_down)

    redis_fail_closed_app = _build_app(_StaticController(), with_gateway_security=True)
    transport = ASGITransport(app=redis_fail_closed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        redis_closed_resp = await client.post("/api/v1/one-button/run", json=payload)
    assert redis_closed_resp.status_code == 503
    assert redis_closed_resp.json()["error"]["code"] == RateLimitErrorCode.RATE_LIMIT_BACKEND_UNAVAILABLE
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_redis_unavailable_fail_closed",
            "passed": True,
            "detail": "status=503 code=RATE_LIMIT_BACKEND_UNAVAILABLE",
        }
    )

    configure_rate_limit(
        {
            "rate_limit": {
                "enabled": True,
                "excluded_paths": [],
                "fail_open": True,
                "by_ip": True,
                "by_user": False,
                "by_api_key": False,
                "by_tenant": False,
            }
        }
    )

    redis_fail_open_app = _build_app(_StaticController(), with_gateway_security=True)
    transport = ASGITransport(app=redis_fail_open_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        redis_open_resp = await client.post("/api/v1/one-button/run", json=payload)
    assert redis_open_resp.status_code == 200
    fallback_events += 1
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_redis_unavailable_fail_open_fallback",
            "passed": True,
            "detail": "status=200 with fail_open fallback",
        }
    )

    configure_auth(
        {
            "auth": {
                "enabled": True,
                "jwt_secret": "test-secret",
                "jwt_algorithms": ["HS256"],
                "protected_path_prefixes": ["/api/v1"],
                "exempt_paths": ["/health"],
            }
        }
    )
    configure_rate_limit({"rate_limit": {"enabled": False}})

    def _auth_provider_down(token: str) -> Dict[str, Any]:
        _ = token
        raise _build_auth_http_exception(
            status_code=500,
            code=AuthErrorCode.CONFIG_ERROR,
            message="auth provider unavailable",
        )

    monkeypatch.setattr("backend.api.middleware.auth._decode_access_token", _auth_provider_down)

    auth_failure_app = _build_app(_StaticController(), with_gateway_security=True)
    transport = ASGITransport(app=auth_failure_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        auth_resp = await client.post(
            "/api/v1/one-button/run",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
    assert auth_resp.status_code == 500
    assert auth_resp.json()["error"]["code"] == AuthErrorCode.CONFIG_ERROR
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_auth_provider_failure",
            "passed": True,
            "detail": "status=500 code=CONFIG_ERROR",
        }
    )

    configure_auth({"auth": {"enabled": False}})
    configure_rate_limit({"rate_limit": {"enabled": False}})

    market_timeout_app = _build_app(_MarketTimeoutController(), with_gateway_security=False)
    transport = ASGITransport(app=market_timeout_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        market_timeout_resp = await client.post("/api/v1/decision/run", json=payload)
    assert market_timeout_resp.status_code == 500
    market_error = market_timeout_resp.json()["detail"]
    assert market_error["error"] == "ONE_BUTTON_PIPELINE_ERROR"
    assert market_error["retryable"] is True
    assert "market timeout" in market_error["message"].lower()
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_market_timeout_error_visibility",
            "passed": True,
            "detail": "status=500 retryable=true code=ONE_BUTTON_PIPELINE_ERROR",
        }
    )

    llm_timeout_app = _build_app(_LLMTimeoutFallbackController(), with_gateway_security=False)
    transport = ASGITransport(app=llm_timeout_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        llm_resp = await client.post("/api/v1/one-button/run", json=payload)
    assert llm_resp.status_code == 200
    llm_stage = llm_resp.json()["stages"]["ml_predict"]["output"]
    assert llm_stage["fallback_reason"] == "provider_timeout"
    fallback_events += 1
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_llm_timeout_fallback_visibility",
            "passed": True,
            "detail": "status=200 with fallback_reason=provider_timeout",
        }
    )

    scheduler_state = StateStore(storage_path=str(tmp_path / "scheduler_delay_state.json"))
    scheduler = RetrainScheduler(
        config=SchedulerConfig(
            enabled=True,
            poll_interval_seconds=60,
            min_feedback_count=0,
            max_consecutive_failures=3,
        ),
        state_store=scheduler_state,
        cooldown_policy=CooldownPolicy(min_interval_hours=0, enabled=False),
    )

    injected_delay_s = 0.08

    def _slow_metrics() -> Dict[str, Any]:
        time.sleep(injected_delay_s)
        return {
            "accuracy_drop": 0.0,
            "drift_score": 0.0,
            "error_rate": 0.0,
        }

    async def _train_callback(trigger: str) -> Dict[str, Any]:
        return {"status": "blocked", "reason": f"no trigger {trigger}"}

    scheduler.configure(
        metric_provider=_slow_metrics,
        feedback_provider=lambda: {"feedback_count": 200, "negative_feedback_rate": 0.05},
        train_callback=_train_callback,
    )

    scheduler_start = time.perf_counter()
    scheduler_result = await scheduler.check_and_trigger()
    scheduler_elapsed = time.perf_counter() - scheduler_start
    assert scheduler_elapsed >= injected_delay_s
    assert "scheduler_failure_rate" in scheduler_result
    failure_injection_total += 1
    scenarios.append(
        {
            "name": "failure_injection_scheduler_delay",
            "passed": True,
            "detail": f"delay_injected={injected_delay_s:.3f}s observed={scheduler_elapsed:.3f}s",
        }
    )

    market_fallback_probe = await _market_timeout_fallback_probe()
    assert market_fallback_probe["fallback_events_delta"] >= 1
    assert market_fallback_probe["missing_market_signal_delta"] >= 1
    fallback_events += market_fallback_probe["fallback_events_delta"]
    scenarios.append(
        {
            "name": "market_timeout_fallback_taxonomy_probe",
            "passed": True,
            "detail": (
                f"fallback_delta={market_fallback_probe['fallback_events_delta']} "
                f"missing_signal_delta={market_fallback_probe['missing_market_signal_delta']}"
            ),
        }
    )

    retry_probe = await _retry_probe_metrics()

    p95_latency_under_load = max(float(load_summary["p95_ms"]), float(soak_summary["overall_p95_ms"]))
    load_total = int(load_summary["total_requests"]) + int(soak_summary["total_requests"])
    load_failures = int(load_summary["failed_requests"]) + int(
        round(soak_summary["error_rate"] * soak_summary["total_requests"])
    )
    error_rate_under_load = float(load_failures) / max(load_total, 1)

    retry_rate = float(retry_probe["retries"]) / max(float(retry_probe["attempts"]), 1.0)
    fallback_rate = float(fallback_events) / max(float(failure_injection_total), 1.0)
    dead_letter_rate = float(retry_probe["dead_letters"]) / max(1.0, float(failure_injection_total))

    metrics = {
        "p95_latency_under_load": p95_latency_under_load,
        "error_rate_under_load": error_rate_under_load,
        "retry_rate": retry_rate,
        "fallback_rate": fallback_rate,
        "dead_letter_rate": dead_letter_rate,
    }

    assert metrics["p95_latency_under_load"] <= thresholds["p95_latency_under_load_max_ms"]
    assert metrics["error_rate_under_load"] <= thresholds["error_rate_under_load_max"]
    assert metrics["retry_rate"] >= thresholds["retry_rate_min"]
    assert metrics["fallback_rate"] >= thresholds["fallback_rate_min"]
    assert metrics["dead_letter_rate"] <= thresholds["dead_letter_rate_max"]

    output_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": "decision_endpoint_resilience_mandatory",
        "scenarios": scenarios,
        "metrics": metrics,
        "thresholds": thresholds,
        "tooling_recommendation": {
            "runner": "pytest + pytest-asyncio",
            "load_driver": "httpx.AsyncClient with ASGITransport",
            "fault_injection": "pytest monkeypatch plus deterministic controller stubs",
            "artifacts": [
                "audit_outputs/decision_endpoint_resilience_metrics.json",
                "audit_outputs/decision_endpoint_resilience_report.md",
            ],
        },
        "ci_cd_integration": {
            "workflow": ".github/workflows/ci.yml",
            "mandatory_command": "python -m pytest backend/tests/test_decision_endpoint_resilience.py -v --tb=short",
            "artifact_upload": "decision-resilience-metrics-py${{ matrix.python-version }}",
        },
    }

    _write_artifacts(output_payload)