# backend/tests/test_observability.py
"""
Tests for the runtime observability system.

Coverage:
  • MetricsCollector: counters, gauges, histograms, Prometheus export
  • HealthCheckService: live probe, full probe, component checks
  • AlertManager: fire, dedup, channels, email channel init
  • Integration: OpsHub wiring
"""

import asyncio
import json
import math
import os
import time

import pytest

# ── MetricsCollector ────────────────────────────────────────

from backend.ops.monitoring.metrics import MetricsCollector, _Histogram


class TestMetricsCollector:
    """Test MetricsCollector core functionality."""

    def test_counter_increment(self):
        mc = MetricsCollector()
        mc.inc("test_counter")
        mc.inc("test_counter")
        mc.inc("test_counter", 3)
        assert mc._counters["test_counter"] == 5.0

    def test_counter_with_labels(self):
        mc = MetricsCollector()
        mc.inc("http_total", labels={"method": "GET", "path": "/"})
        mc.inc("http_total", labels={"method": "POST", "path": "/"})
        assert mc._counters['http_total{method="GET",path="/"}'] == 1.0
        assert mc._counters['http_total{method="POST",path="/"}'] == 1.0

    def test_gauge_set_and_get(self):
        mc = MetricsCollector()
        mc.set_gauge("cpu", 42.5)
        assert mc.get_gauge("cpu") == 42.5
        mc.set_gauge("cpu", 10.0)
        assert mc.get_gauge("cpu") == 10.0

    def test_gauge_default_zero(self):
        mc = MetricsCollector()
        assert mc.get_gauge("nonexistent") == 0.0

    def test_histogram_observe(self):
        mc = MetricsCollector()
        mc.observe_latency("test_hist", 0.05)
        mc.observe_latency("test_hist", 0.5)
        mc.observe_latency("test_hist", 2.0)
        snap = mc._histograms["test_hist"].snapshot()
        assert snap["count"] == 3
        assert snap["sum"] > 0

    def test_record_request(self):
        mc = MetricsCollector()
        mc.record_request("GET", "/health", 200, 0.01)
        mc.record_request("POST", "/api", 500, 0.5)
        assert mc._counters["http_requests_total"] == 0  # labelled
        total = sum(
            v for k, v in mc._counters.items()
            if k.startswith("http_requests_total")
        )
        assert total == 2

    def test_error_rate_zero(self):
        mc = MetricsCollector()
        assert mc.error_rate() == 0.0

    def test_error_rate_nonzero(self):
        mc = MetricsCollector()
        for _ in range(9):
            mc.record_request("GET", "/ok", 200, 0.01)
        mc.record_request("GET", "/bad", 500, 0.01)
        rate = mc.error_rate()
        assert rate > 0
        assert rate <= 1.0

    def test_drift_recording(self):
        mc = MetricsCollector()
        mc.record_drift(0.42, True)
        assert mc.get_gauge("data_drift_score") == 0.42
        assert mc.get_gauge("data_drift_detected") == 1.0

    def test_browser_leak_recording(self):
        mc = MetricsCollector()
        mc.record_browser_leak({"memory_leak": True, "severity": "high"})
        assert mc.get_gauge("browser_memory_leak") == 1.0
        assert mc.get_gauge("browser_leak_severity") == 3.0

    def test_export_prometheus_format(self):
        mc = MetricsCollector()
        mc.set_gauge("test_g", 1.0)
        mc.inc("test_c")
        output = mc.export_prometheus()
        assert "test_g 1.0" in output
        assert "test_c" in output
        assert "# TYPE" in output

    def test_export_json(self):
        mc = MetricsCollector()
        mc.set_gauge("g1", 5.0)
        mc.inc("c1", 3)
        j = mc.export_json()
        assert "gauges" in j
        assert "counters" in j
        assert "histograms" in j
        assert "error_rate" in j
        assert "uptime_seconds" in j
        assert j["gauges"]["g1"] == 5.0

    def test_series_recording(self):
        mc = MetricsCollector()
        mc.set_gauge("s1", 1.0)
        mc.set_gauge("s1", 2.0)
        mc.set_gauge("s1", 3.0)
        series = mc.get_series("s1")
        assert len(series) == 3
        assert series[-1]["value"] == 3.0

    def test_process_metrics_no_crash(self):
        mc = MetricsCollector()
        result = mc.collect_process_metrics()
        # Should return a dict (empty if psutil missing)
        assert isinstance(result, dict)

    def test_system_metrics_no_crash(self):
        mc = MetricsCollector()
        result = mc.collect_system_metrics()
        assert isinstance(result, dict)

    def test_refresh_infra_gauges(self):
        mc = MetricsCollector()
        mc.refresh_infra_gauges()
        assert mc.get_gauge("process_uptime_seconds") > 0


class TestHistogram:
    """Test the internal _Histogram class."""

    def test_observe_single(self):
        h = _Histogram("test")
        h.observe(0.1)
        snap = h.snapshot()
        assert snap["count"] == 1
        assert snap["sum"] == pytest.approx(0.1)

    def test_buckets(self):
        h = _Histogram("test")
        h.observe(0.001)
        h.observe(100.0)
        snap = h.snapshot()
        assert snap["count"] == 2
        assert snap["buckets"]["0.005"] == 1  # 0.001 <= 0.005
        assert snap["buckets"]["+Inf"] == 2   # everything falls in +Inf

    def test_prom_format(self):
        h = _Histogram("lat")
        h.observe(0.5)
        prom = h.to_prom()
        assert "lat_bucket" in prom
        assert "lat_sum" in prom
        assert "lat_count 1" in prom


# ── HealthCheckService ──────────────────────────────────────

from backend.ops.monitoring.health import HealthCheckService, HealthStatus


class TestHealthLive:
    """Test liveness probe."""

    @pytest.mark.asyncio
    async def test_live_returns_alive(self):
        svc = HealthCheckService()
        result = await svc.live()
        assert result["status"] == "alive"
        assert result["service"] == "hdss-backend"
        assert "pid" in result
        assert "uptime_seconds" in result
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_live_is_fast(self):
        svc = HealthCheckService()
        start = time.monotonic()
        await svc.live()
        elapsed = (time.monotonic() - start) * 1000
        assert elapsed < 50  # should be < 1ms but allow margin


class TestHealthFull:
    """Test full readiness probe."""

    @pytest.mark.asyncio
    async def test_full_with_no_checks(self):
        svc = HealthCheckService()
        result = await svc.check_all()
        assert result["status"] == "healthy"
        assert "uptime_seconds" in result
        assert "components" in result

    @pytest.mark.asyncio
    async def test_full_with_healthy_check(self):
        svc = HealthCheckService()

        async def ok_check():
            return {"status": "healthy", "message": "OK"}

        svc.register_check("test_ok", ok_check)
        result = await svc.check_all()
        assert result["status"] == "healthy"
        assert "test_ok" in result["components"]

    @pytest.mark.asyncio
    async def test_full_with_unhealthy_check(self):
        svc = HealthCheckService()

        async def bad_check():
            raise RuntimeError("broken")

        svc.register_check("bad", bad_check)
        result = await svc.check_all()
        assert result["status"] == "unhealthy"
        assert result["components"]["bad"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_full_with_metrics(self):
        svc = HealthCheckService()
        mc = MetricsCollector()
        svc.set_metrics(mc)
        result = await svc.check_all()
        assert "metrics" in result

    @pytest.mark.asyncio
    async def test_timeout_check(self):
        svc = HealthCheckService()

        async def slow_check():
            await asyncio.sleep(20)

        svc.register_check("slow", slow_check)
        result = await svc.check_all()
        assert result["components"]["slow"]["status"] == "unhealthy"
        assert "timed out" in result["components"]["slow"]["message"]

    @pytest.mark.asyncio
    async def test_degraded_status(self):
        svc = HealthCheckService()

        async def degraded_check():
            return {"status": "degraded", "message": "partial"}

        svc.register_check("d", degraded_check)
        result = await svc.check_all()
        assert result["status"] == "degraded"


class TestBuiltinChecks:
    """Test built-in health check functions."""

    @pytest.mark.asyncio
    async def test_disk_space(self):
        result = await HealthCheckService.check_disk_space()
        assert result["status"] in ("healthy", "unhealthy")
        assert "details" in result

    @pytest.mark.asyncio
    async def test_memory(self):
        result = await HealthCheckService.check_memory()
        assert result["status"] in ("healthy", "degraded", "unhealthy", "unknown")

    @pytest.mark.asyncio
    async def test_data_dir(self):
        result = await HealthCheckService.check_data_dir()
        assert result["status"] in ("healthy", "unhealthy")


# ── AlertManager ────────────────────────────────────────────

from backend.ops.monitoring.alerts import (
    AlertManager,
    AlertSeverity,
    Alert,
    LogAlertChannel,
    FileAlertChannel,
    WebhookAlertChannel,
    EmailAlertChannel,
)


class TestAlertManager:

    @pytest.mark.asyncio
    async def test_fire_basic(self):
        mgr = AlertManager(cooldown_seconds=0)
        delivered = await mgr.fire(
            title="Test",
            message="Hello",
            severity=AlertSeverity.INFO,
        )
        assert delivered is True
        assert len(mgr._history) == 1

    @pytest.mark.asyncio
    async def test_dedup_within_cooldown(self):
        mgr = AlertManager(cooldown_seconds=600)
        await mgr.fire(title="Same", message="1", source="x")
        result = await mgr.fire(title="Same", message="2", source="x")
        assert result is False  # deduplicated
        assert len(mgr._history) == 1

    @pytest.mark.asyncio
    async def test_force_bypasses_dedup(self):
        mgr = AlertManager(cooldown_seconds=600)
        await mgr.fire(title="Same", message="1", source="x")
        result = await mgr.fire(title="Same", message="2", source="x", force=True)
        assert result is True
        assert len(mgr._history) == 2

    @pytest.mark.asyncio
    async def test_fire_if_true(self):
        mgr = AlertManager(cooldown_seconds=0)
        result = await mgr.fire_if(True, title="Cond", message="yes")
        assert result is True

    @pytest.mark.asyncio
    async def test_fire_if_false(self):
        mgr = AlertManager(cooldown_seconds=0)
        result = await mgr.fire_if(False, title="Cond", message="no")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_recent(self):
        mgr = AlertManager(cooldown_seconds=0)
        await mgr.fire(title="A", message="a", severity=AlertSeverity.WARNING)
        await mgr.fire(title="B", message="b", severity=AlertSeverity.CRITICAL)
        recent = mgr.get_recent(hours=1)
        assert len(recent) == 2

    def test_get_summary(self):
        mgr = AlertManager()
        summary = mgr.get_summary()
        assert "total_alerts" in summary
        assert "by_severity" in summary
        assert "channels" in summary

    def test_alert_to_dict(self):
        a = Alert(title="T", message="M", severity=AlertSeverity.CRITICAL)
        d = a.to_dict()
        assert d["title"] == "T"
        assert d["severity"] == "critical"

    def test_email_channel_init(self):
        ch = EmailAlertChannel(
            smtp_host="smtp.example.com",
            from_addr="a@b.com",
            to_addrs=["c@d.com"],
        )
        assert ch.smtp_host == "smtp.example.com"
        assert ch.to_addrs == ["c@d.com"]

    def test_email_channel_no_config_skips(self):
        ch = EmailAlertChannel()
        # Without SMTP config, send should return False
        loop = asyncio.new_event_loop()
        alert = Alert(title="T", message="M")
        result = loop.run_until_complete(ch.send(alert))
        loop.close()
        assert result is False


# ── OpsHub wiring ───────────────────────────────────────────

from backend.ops.integration import OpsHub


class TestOpsHubObservability:
    """Test that OpsHub exposes observability services."""

    def test_metrics_accessor(self):
        hub = OpsHub()
        mc = hub.metrics
        assert isinstance(mc, MetricsCollector)

    def test_metrics_singleton(self):
        hub = OpsHub()
        assert hub.metrics is hub.metrics

    def test_health_has_live(self):
        hub = OpsHub()
        assert hasattr(hub.health, "live")

    def test_health_has_set_metrics(self):
        hub = OpsHub()
        assert hasattr(hub.health, "set_metrics")

    @pytest.mark.asyncio
    async def test_startup_wires_metrics(self):
        hub = OpsHub()
        await hub.startup()
        assert hub.health._metrics is hub.metrics
        await hub.shutdown()


# ── Prometheus format correctness ───────────────────────────

class TestPrometheusExport:
    """Validate the exported Prometheus text format."""

    def test_gauge_lines(self):
        mc = MetricsCollector()
        mc.set_gauge("my_gauge", 99)
        prom = mc.export_prometheus()
        assert "# TYPE my_gauge gauge" in prom
        assert "my_gauge 99" in prom

    def test_counter_lines(self):
        mc = MetricsCollector()
        mc.inc("my_counter", 5)
        prom = mc.export_prometheus()
        assert "# TYPE my_counter counter" in prom
        assert "my_counter 5" in prom

    def test_histogram_lines(self):
        mc = MetricsCollector()
        mc.observe_latency("http_request_duration_seconds", 0.1)
        prom = mc.export_prometheus()
        assert "# TYPE http_request_duration_seconds histogram" in prom
        assert "http_request_duration_seconds_bucket" in prom
        assert "http_request_duration_seconds_sum" in prom
        assert "http_request_duration_seconds_count 1" in prom

    def test_no_empty_export(self):
        mc = MetricsCollector()
        mc.refresh_infra_gauges()
        prom = mc.export_prometheus()
        assert len(prom) > 50  # at least uptime gauge


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
