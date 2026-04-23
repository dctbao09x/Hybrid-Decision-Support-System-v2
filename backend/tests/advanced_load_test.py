#!/usr/bin/env python3
"""
Advanced Load Test Suite for SRE Validation
============================================

Multi-stage load test with real-time metrics collection.
Tests at increasing RPS levels and generates detailed report.

Usage:
    python backend/tests/advanced_load_test.py [--duration 60] [--max-rps 150]
"""

import asyncio
import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    print("[ERROR] aiohttp required: pip install aiohttp")
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class StageResult:
    """Results for a single test stage."""
    target_rps: int
    actual_rps: float
    total_requests: int
    successful: int
    failed: int
    success_rate: float
    latencies_ms: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    
    # Percentiles (calculated after test)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    
    def calculate_percentiles(self):
        if not self.latencies_ms:
            return
        sorted_lat = sorted(self.latencies_ms)
        n = len(sorted_lat)
        self.min_ms = sorted_lat[0]
        self.max_ms = sorted_lat[-1]
        self.avg_ms = statistics.mean(sorted_lat)
        self.p50_ms = sorted_lat[int(n * 0.50)]
        self.p95_ms = sorted_lat[int(n * 0.95)]
        self.p99_ms = sorted_lat[min(int(n * 0.99), n - 1)]
    
    def to_dict(self) -> dict:
        return {
            "target_rps": self.target_rps,
            "actual_rps": round(self.actual_rps, 1),
            "total_requests": self.total_requests,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate_pct": round(self.success_rate, 2),
            "latency_ms": {
                "min": round(self.min_ms, 2),
                "avg": round(self.avg_ms, 2),
                "p50": round(self.p50_ms, 2),
                "p95": round(self.p95_ms, 2),
                "p99": round(self.p99_ms, 2),
                "max": round(self.max_ms, 2),
            },
            "errors": dict(sorted(self.errors.items(), key=lambda x: -x[1])[:5]),
        }


async def run_load_stage(
    target_rps: int,
    duration_seconds: int,
    endpoint: str = "/api/v1/health",
    max_concurrent: int = 500,
) -> StageResult:
    """
    Run a single load test stage at specified RPS.
    
    Args:
        target_rps: Target requests per second
        duration_seconds: Test duration
        endpoint: API endpoint to test
        max_concurrent: Max concurrent connections
    """
    result = StageResult(
        target_rps=target_rps,
        actual_rps=0.0,
        total_requests=0,
        successful=0,
        failed=0,
        success_rate=0.0,
    )
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    connector = aiohttp.TCPConnector(
        limit=max_concurrent,
        limit_per_host=max_concurrent,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        
        async def do_request():
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    async with session.get(f"{BASE_URL}{endpoint}") as resp:
                        latency = (time.perf_counter() - t0) * 1000
                        if resp.status == 200:
                            result.successful += 1
                            result.latencies_ms.append(latency)
                        else:
                            result.failed += 1
                            err = f"HTTP_{resp.status}"
                            result.errors[err] = result.errors.get(err, 0) + 1
                except asyncio.TimeoutError:
                    result.failed += 1
                    result.errors["Timeout"] = result.errors.get("Timeout", 0) + 1
                except aiohttp.ClientConnectorError:
                    result.failed += 1
                    result.errors["ConnectorError"] = result.errors.get("ConnectorError", 0) + 1
                except Exception as e:
                    result.failed += 1
                    err = type(e).__name__
                    result.errors[err] = result.errors.get(err, 0) + 1
        
        start_time = time.perf_counter()
        end_time = start_time + duration_seconds
        interval = 1.0 / target_rps if target_rps > 0 else 0.01
        next_request_time = start_time
        pending: List[asyncio.Task] = []
        
        while time.perf_counter() < end_time:
            now = time.perf_counter()
            
            # Schedule requests at target rate
            while next_request_time <= now and next_request_time < end_time:
                pending.append(asyncio.create_task(do_request()))
                result.total_requests += 1
                next_request_time += interval
            
            # Cleanup completed tasks
            pending = [t for t in pending if not t.done()]
            
            await asyncio.sleep(0.001)
        
        # Wait for remaining
        if pending:
            await asyncio.wait(pending, timeout=10)
        
        elapsed = time.perf_counter() - start_time
    
    # Calculate metrics
    result.actual_rps = result.total_requests / elapsed if elapsed > 0 else 0
    total = result.successful + result.failed
    result.success_rate = (result.successful / total * 100) if total > 0 else 0
    result.calculate_percentiles()
    
    return result


async def run_multi_stage_test(
    stages: List[int],
    duration_per_stage: int = 30,
    cooldown: int = 5,
) -> List[StageResult]:
    """Run multiple load test stages with cooldown between."""
    
    results = []
    
    for i, target_rps in enumerate(stages):
        print(f"\n{'='*60}")
        print(f"STAGE {i+1}/{len(stages)}: {target_rps} RPS")
        print(f"{'='*60}")
        
        result = await run_load_stage(
            target_rps=target_rps,
            duration_seconds=duration_per_stage,
        )
        
        results.append(result)
        
        # Print interim results
        print(f"  Actual RPS: {result.actual_rps:.1f}")
        print(f"  Success Rate: {result.success_rate:.1f}%")
        print(f"  P95 Latency: {result.p95_ms:.1f}ms")
        print(f"  P99 Latency: {result.p99_ms:.1f}ms")
        
        if result.errors:
            print(f"  Top Errors: {list(result.errors.items())[:3]}")
        
        # SLA check
        sla_pass = result.success_rate >= 99.5 and result.p95_ms <= 100
        status = "PASS" if sla_pass else "FAIL"
        print(f"  SLA Status: [{status}]")
        
        # Cooldown between stages
        if i < len(stages) - 1:
            print(f"\n  Cooldown: {cooldown}s...")
            await asyncio.sleep(cooldown)
    
    return results


def print_summary(results: List[StageResult]):
    """Print final summary table."""
    
    print("\n" + "=" * 80)
    print("LOAD TEST SUMMARY")
    print("=" * 80)
    
    print(f"\n{'Target':>8} {'Actual':>8} {'Success':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'SLA':>6}")
    print("-" * 80)
    
    for r in results:
        sla = "PASS" if r.success_rate >= 99.5 and r.p95_ms <= 100 else "FAIL"
        print(
            f"{r.target_rps:>7}  {r.actual_rps:>7.1f}  {r.success_rate:>7.1f}%  "
            f"{r.p50_ms:>7.1f}  {r.p95_ms:>7.1f}  {r.p99_ms:>7.1f}  [{sla}]"
        )
    
    print("-" * 80)
    
    # Overall verdict
    passing_stages = [r for r in results if r.success_rate >= 99.5 and r.p95_ms <= 100]
    max_passing_rps = max((r.target_rps for r in passing_stages), default=0)
    
    print(f"\nMax Sustainable RPS (SLA compliant): {max_passing_rps}")
    
    target_met = any(r.target_rps >= 100 and r.success_rate >= 99.5 and r.p95_ms <= 100 for r in results)
    print(f"\n{'='*80}")
    print(f"TARGET (≥100 RPS, 99.5% success, p95<100ms): {'ACHIEVED' if target_met else 'NOT MET'}")
    print(f"{'='*80}")
    
    return target_met


def main():
    parser = argparse.ArgumentParser(description="Advanced Load Test Suite")
    parser.add_argument("--duration", type=int, default=30, help="Duration per stage (seconds)")
    parser.add_argument("--cooldown", type=int, default=5, help="Cooldown between stages")
    parser.add_argument("--max-rps", type=int, default=150, help="Maximum RPS to test")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file")
    args = parser.parse_args()
    
    # Test stages
    stages = [50, 75, 100, 125, 150]
    stages = [s for s in stages if s <= args.max_rps]
    
    print("=" * 60)
    print("ADVANCED LOAD TEST SUITE")
    print("=" * 60)
    print(f"Start Time: {datetime.now().isoformat()}")
    print(f"Base URL: {BASE_URL}")
    print(f"Stages: {stages}")
    print(f"Duration per stage: {args.duration}s")
    
    # Run tests
    results = asyncio.run(run_multi_stage_test(
        stages=stages,
        duration_per_stage=args.duration,
        cooldown=args.cooldown,
    ))
    
    # Print summary
    target_met = print_summary(results)
    
    # Save JSON output
    if args.output:
        output = {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "stages": stages,
                "duration_per_stage": args.duration,
            },
            "results": [r.to_dict() for r in results],
            "target_met": target_met,
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to: {args.output}")
    
    return 0 if target_met else 1


if __name__ == "__main__":
    sys.exit(main())
