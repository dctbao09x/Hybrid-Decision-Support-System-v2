# backend/ops/tests/test_supervisor.py
"""
Tests for the PipelineSupervisor auto-restart system.
"""

import asyncio

import pytest

from backend.ops.orchestration.supervisor import (
    PipelineSupervisor,
    RestartPolicy,
    SupervisedState,
)


class TestPipelineSupervisor:
    """Tests for PipelineSupervisor."""

    @pytest.mark.asyncio
    async def test_register_and_clean_exit(self):
        """A function that exits cleanly should not restart."""
        calls = []

        async def my_func():
            calls.append(1)

        sup = PipelineSupervisor()
        sup.register("test", my_func)
        await sup.start("test")
        await asyncio.sleep(0.1)

        status = sup.get_status()
        assert "test" in status
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_auto_restart_on_crash(self):
        """Process should auto-restart up to max_restarts."""
        attempt = {"count": 0}

        async def crashing_func():
            attempt["count"] += 1
            raise RuntimeError(f"crash #{attempt['count']}")

        policy = RestartPolicy(max_restarts=3, base_backoff_seconds=0.05, max_backoff_seconds=0.1)
        sup = PipelineSupervisor()
        sup.register("crasher", crashing_func, policy=policy)
        await sup.start("crasher")

        # Wait for retries to exhaust
        await asyncio.sleep(1.5)

        status = sup.get_status()
        assert status["crasher"]["state"] == SupervisedState.FAILED.value
        assert attempt["count"] > 1

    @pytest.mark.asyncio
    async def test_manual_restart_resets_counter(self):
        """Manual restart should reset the restart counter."""
        calls = []

        async def func():
            calls.append(1)

        sup = PipelineSupervisor()
        sup.register("resettable", func)
        await sup.start("resettable")
        await asyncio.sleep(0.1)

        await sup.restart("resettable")
        await asyncio.sleep(0.1)

        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Shutdown should stop all processes."""
        running = {"active": True}

        async def long_runner():
            while running["active"]:
                await asyncio.sleep(0.01)

        sup = PipelineSupervisor()
        sup.register("runner", long_runner)
        await sup.start("runner")
        await asyncio.sleep(0.1)

        await sup.shutdown()
        running["active"] = False

        status = sup.get_status()
        assert status["runner"]["state"] == SupervisedState.STOPPED.value

    @pytest.mark.asyncio
    async def test_hooks_called_on_crash(self):
        """Event hooks should fire on crash."""
        events = []

        async def crasher():
            raise ValueError("boom")

        async def on_crash(name, error):
            events.append(("crash", name, str(error)))

        async def on_max(name):
            events.append(("max", name))

        policy = RestartPolicy(max_restarts=1, base_backoff_seconds=0.05, cooldown_after_max=0.1)
        sup = PipelineSupervisor()
        sup.set_hooks(on_crash=on_crash, on_max_restart=on_max)
        sup.register("hooked", crasher, policy=policy)
        await sup.start("hooked")
        await asyncio.sleep(1.0)

        crash_events = [e for e in events if e[0] == "crash"]
        max_events = [e for e in events if e[0] == "max"]
        assert len(crash_events) >= 1
        assert len(max_events) == 1

    @pytest.mark.asyncio
    async def test_get_process_detail(self):
        """get_process_detail should return detailed info."""
        async def noop():
            pass

        sup = PipelineSupervisor()
        sup.register("detail_test", noop)
        await sup.start("detail_test")
        await asyncio.sleep(0.1)

        detail = sup.get_process_detail("detail_test")
        assert detail["name"] == "detail_test"
        assert "recent_events" in detail
        assert len(detail["recent_events"]) > 0
