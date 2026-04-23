#!/usr/bin/env python3
"""Extended load test to find breaking point."""
import asyncio
import time
import aiohttp

BASE_URL = "http://127.0.0.1:8000"

async def test_rps(target_rps: int, duration: int = 15):
    success = fail = 0
    latencies = []
    
    connector = aiohttp.TCPConnector(limit=200, keepalive_timeout=30)
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start = time.perf_counter()
        end = start + duration
        interval = 1.0 / target_rps
        next_t = start
        pending = []
        
        async def do_request():
            nonlocal success, fail
            t0 = time.perf_counter()
            try:
                async with session.get(f"{BASE_URL}/api/v1/health") as r:
                    lat = (time.perf_counter() - t0) * 1000
                    if r.status == 200:
                        success += 1
                        latencies.append(lat)
                    else:
                        fail += 1
            except:
                fail += 1
        
        while time.perf_counter() < end:
            now = time.perf_counter()
            while next_t <= now and next_t < end:
                pending.append(asyncio.create_task(do_request()))
                next_t += interval
            pending = [t for t in pending if not t.done()]
            await asyncio.sleep(0.001)
        
        if pending:
            await asyncio.wait(pending, timeout=10)
    
    total = success + fail
    rate = (success / total * 100) if total > 0 else 0
    avg_lat = (sum(latencies) / len(latencies)) if latencies else 0
    p95 = sorted(latencies)[int(len(latencies)*0.95)] if len(latencies) > 20 else avg_lat
    p99 = sorted(latencies)[int(len(latencies)*0.99)] if len(latencies) > 100 else p95
    elapsed = time.perf_counter() - start
    actual = total / elapsed if elapsed > 0 else 0
    
    print(f"Target: {target_rps:3d} | Actual: {actual:5.1f} | Success: {rate:5.1f}% | p95: {p95:6.1f}ms | p99: {p99:6.1f}ms | n={total}")
    return rate, p95, p99

async def main():
    print("=" * 70)
    print("HIGH LOAD CAPACITY TEST")
    print("=" * 70)
    print()
    
    results = []
    for rps in [40, 50, 60, 70, 80, 100, 120]:
        rate, p95, p99 = await test_rps(rps, duration=10)
        results.append((rps, rate, p95, p99))
        if rate < 95:
            print(f">>> Breaking point found at {rps} RPS <<<")
            break
        await asyncio.sleep(1)
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    # Find max sustainable
    max_sustainable = 0
    for rps, rate, p95, p99 in results:
        if rate >= 99.5 and p95 <= 500:
            max_sustainable = rps
    
    print(f"Max sustainable RPS (99.5% success, p95<500ms): {max_sustainable}")
    print()
    
    # SLA verdict
    print("SLA VERDICT:")
    for rps, rate, p95, p99 in results:
        sla_pass = rate >= 99.5 and p95 <= 500
        status = "PASS" if sla_pass else "FAIL"
        print(f"  [{status}] {rps} RPS: {rate:.1f}% success, p95={p95:.1f}ms")

if __name__ == "__main__":
    asyncio.run(main())
