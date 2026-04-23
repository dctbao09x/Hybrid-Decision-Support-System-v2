#!/usr/bin/env python3
"""
SRE Load Test Suite
===================

Tests backend resilience under high concurrency.
Target: 100+ RPS for configurable duration.
"""

import asyncio
import time
import statistics
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class RequestResult:
    endpoint: str
    status_code: int
    latency_ms: float
    success: bool
    error: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class LoadTestReport:
    """Load test aggregated results."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_duration_seconds: float = 0.0
    target_rps: int = 0
    actual_rps: float = 0.0
    
    latencies_ms: List[float] = field(default_factory=list)
    status_codes: Dict[int, int] = field(default_factory=dict)
    errors: Dict[str, int] = field(default_factory=dict)
    
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    min_ms: float = 0.0
    avg_ms: float = 0.0
    
    def calculate_percentiles(self):
        if self.latencies_ms:
            sorted_latencies = sorted(self.latencies_ms)
            n = len(sorted_latencies)
            self.min_ms = sorted_latencies[0]
            self.max_ms = sorted_latencies[-1]
            self.avg_ms = statistics.mean(sorted_latencies)
            self.p50_ms = sorted_latencies[int(n * 0.50)]
            self.p95_ms = sorted_latencies[int(n * 0.95)]
            self.p99_ms = sorted_latencies[int(n * 0.99)] if n >= 100 else sorted_latencies[-1]
    
    def to_dict(self) -> Dict[str, Any]:
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        return {
            "summary": {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate_pct": round(success_rate, 2),
                "duration_seconds": round(self.total_duration_seconds, 2),
                "target_rps": self.target_rps,
                "actual_rps": round(self.actual_rps, 2),
            },
            "latency_ms": {
                "min": round(self.min_ms, 2),
                "avg": round(self.avg_ms, 2),
                "p50": round(self.p50_ms, 2),
                "p95": round(self.p95_ms, 2),
                "p99": round(self.p99_ms, 2),
                "max": round(self.max_ms, 2),
            },
            "status_codes": self.status_codes,
            "top_errors": dict(sorted(self.errors.items(), key=lambda x: -x[1])[:5]),
        }


def sync_request(endpoint: str) -> RequestResult:
    """Synchronous HTTP request using urllib."""
    start = time.perf_counter()
    try:
        req = urllib.request.Request(f"{BASE_URL}{endpoint}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestResult(
                endpoint=endpoint,
                status_code=resp.status,
                latency_ms=latency_ms,
                success=200 <= resp.status < 400,
            )
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            endpoint=endpoint,
            status_code=e.code,
            latency_ms=latency_ms,
            success=False,
            error=f"HTTP {e.code}: {str(e.reason)[:50]}",
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        error_type = type(e).__name__
        return RequestResult(
            endpoint=endpoint,
            status_code=0,
            latency_ms=latency_ms,
            success=False,
            error=f"{error_type}: {str(e)[:50]}",
        )


def run_sync_load_test(
    endpoints: List[str],
    target_rps: int = 100,
    duration_seconds: int = 60,
    max_workers: int = 50,
) -> LoadTestReport:
    """Run load test using ThreadPoolExecutor (fallback if no aiohttp)."""
    
    print(f"\n=== SYNC LOAD TEST ===")
    print(f"Target: {target_rps} RPS for {duration_seconds}s")
    print(f"Endpoints: {endpoints}")
    print(f"Workers: {max_workers}")
    print()
    
    report = LoadTestReport(target_rps=target_rps)
    results: List[RequestResult] = []
    
    start_time = time.perf_counter()
    end_time = start_time + duration_seconds
    request_interval = 1.0 / target_rps if target_rps > 0 else 0.01
    
    next_request_time = start_time
    endpoint_idx = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        
        while time.perf_counter() < end_time:
            current_time = time.perf_counter()
            
            # Submit requests at target rate
            while next_request_time <= current_time and next_request_time < end_time:
                endpoint = endpoints[endpoint_idx % len(endpoints)]
                endpoint_idx += 1
                futures.append(executor.submit(sync_request, endpoint))
                next_request_time += request_interval
            
            # Collect completed results
            completed = [f for f in futures if f.done()]
            for f in completed:
                try:
                    results.append(f.result())
                except Exception:
                    pass
            futures = [f for f in futures if not f.done()]
            
            # Progress update every 10 seconds
            elapsed = current_time - start_time
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                current_rps = len(results) / elapsed if elapsed > 0 else 0
                print(f"  Progress: {int(elapsed)}s, requests={len(results)}, rps={current_rps:.1f}")
            
            time.sleep(0.001)  # Prevent busy loop
        
        # Wait for remaining futures
        for f in futures:
            try:
                results.append(f.result(timeout=5))
            except Exception:
                pass
    
    report.total_duration_seconds = time.perf_counter() - start_time
    
    # Aggregate results
    for r in results:
        report.total_requests += 1
        report.latencies_ms.append(r.latency_ms)
        report.status_codes[r.status_code] = report.status_codes.get(r.status_code, 0) + 1
        
        if r.success:
            report.successful_requests += 1
        else:
            report.failed_requests += 1
            if r.error:
                report.errors[r.error] = report.errors.get(r.error, 0) + 1
    
    if report.total_duration_seconds > 0:
        report.actual_rps = report.total_requests / report.total_duration_seconds
    
    report.calculate_percentiles()
    return report


async def async_request(session: "aiohttp.ClientSession", endpoint: str) -> RequestResult:
    """Async HTTP request using aiohttp."""
    start = time.perf_counter()
    try:
        async with session.get(f"{BASE_URL}{endpoint}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestResult(
                endpoint=endpoint,
                status_code=resp.status,
                latency_ms=latency_ms,
                success=200 <= resp.status < 400,
            )
    except asyncio.TimeoutError:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            endpoint=endpoint,
            status_code=0,
            latency_ms=latency_ms,
            success=False,
            error="TimeoutError: Request timed out",
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        error_type = type(e).__name__
        return RequestResult(
            endpoint=endpoint,
            status_code=0,
            latency_ms=latency_ms,
            success=False,
            error=f"{error_type}: {str(e)[:50]}",
        )


async def run_async_load_test(
    endpoints: List[str],
    target_rps: int = 100,
    duration_seconds: int = 60,
    max_concurrent: int = 200,
) -> LoadTestReport:
    """Run load test using asyncio + aiohttp."""
    
    print(f"\n=== ASYNC LOAD TEST ===")
    print(f"Target: {target_rps} RPS for {duration_seconds}s")
    print(f"Endpoints: {endpoints}")
    print(f"Max concurrent: {max_concurrent}")
    print()
    
    report = LoadTestReport(target_rps=target_rps)
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def bounded_request(session, endpoint):
        async with semaphore:
            return await async_request(session, endpoint)
    
    connector = aiohttp.TCPConnector(limit=max_concurrent, limit_per_host=max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        
        start_time = time.perf_counter()
        end_time = start_time + duration_seconds
        request_interval = 1.0 / target_rps if target_rps > 0 else 0.01
        
        tasks = []
        results = []
        next_request_time = start_time
        endpoint_idx = 0
        last_progress = 0
        
        while time.perf_counter() < end_time:
            current_time = time.perf_counter()
            
            # Schedule requests at target rate
            while next_request_time <= current_time and next_request_time < end_time:
                endpoint = endpoints[endpoint_idx % len(endpoints)]
                endpoint_idx += 1
                tasks.append(asyncio.create_task(bounded_request(session, endpoint)))
                next_request_time += request_interval
            
            # Collect completed tasks
            done_tasks = [t for t in tasks if t.done()]
            for t in done_tasks:
                try:
                    results.append(t.result())
                except Exception:
                    pass
            tasks = [t for t in tasks if not t.done()]
            
            # Progress update every 10 seconds
            elapsed = int(current_time - start_time)
            if elapsed > last_progress and elapsed % 10 == 0:
                last_progress = elapsed
                current_rps = len(results) / (current_time - start_time) if (current_time - start_time) > 0 else 0
                print(f"  Progress: {elapsed}s, requests={len(results)}, pending={len(tasks)}, rps={current_rps:.1f}")
            
            await asyncio.sleep(0.001)
        
        # Wait for remaining tasks
        if tasks:
            done, _ = await asyncio.wait(tasks, timeout=10)
            for t in done:
                try:
                    results.append(t.result())
                except Exception:
                    pass
        
        report.total_duration_seconds = time.perf_counter() - start_time
    
    # Aggregate results
    for r in results:
        report.total_requests += 1
        report.latencies_ms.append(r.latency_ms)
        report.status_codes[r.status_code] = report.status_codes.get(r.status_code, 0) + 1
        
        if r.success:
            report.successful_requests += 1
        else:
            report.failed_requests += 1
            if r.error:
                report.errors[r.error] = report.errors.get(r.error, 0) + 1
    
    if report.total_duration_seconds > 0:
        report.actual_rps = report.total_requests / report.total_duration_seconds
    
    report.calculate_percentiles()
    return report


def main():
    """Run load test and print results."""
    
    ENDPOINTS = [
        "/api/v1/health",
        "/api/v1/health/ready",
        "/api/v1/resilience/bulkheads",
        "/api/v1/resilience/timeouts",
    ]
    
    TARGET_RPS = 100
    DURATION_SECONDS = 60  # 1 minute for quick test, increase for full test
    
    print("=" * 60)
    print("SRE LOAD TEST SUITE")
    print("=" * 60)
    print(f"Start time: {datetime.now().isoformat()}")
    print(f"Base URL: {BASE_URL}")
    
    if HAS_AIOHTTP:
        report = asyncio.run(run_async_load_test(
            endpoints=ENDPOINTS,
            target_rps=TARGET_RPS,
            duration_seconds=DURATION_SECONDS,
        ))
    else:
        print("\n[INFO] aiohttp not available, using sync fallback")
        report = run_sync_load_test(
            endpoints=ENDPOINTS,
            target_rps=TARGET_RPS,
            duration_seconds=DURATION_SECONDS,
        )
    
    print("\n" + "=" * 60)
    print("LOAD TEST RESULTS")
    print("=" * 60)
    print(json.dumps(report.to_dict(), indent=2))
    
    # SLA Check
    success_rate = (report.successful_requests / report.total_requests * 100) if report.total_requests > 0 else 0
    print("\n" + "=" * 60)
    print("SLA VALIDATION")
    print("=" * 60)
    
    sla_checks = {
        "success_rate >= 99.5%": success_rate >= 99.5,
        "p95_latency <= 500ms": report.p95_ms <= 500,
        "p99_latency <= 1000ms": report.p99_ms <= 1000,
        "actual_rps >= 80% target": report.actual_rps >= (TARGET_RPS * 0.8),
    }
    
    all_passed = all(sla_checks.values())
    
    for check, passed in sla_checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}")
    
    print(f"\n  OVERALL: {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
