#!/usr/bin/env python3
"""Quick load calibration test."""
import asyncio
import time
import aiohttp
import sys

BASE_URL = "http://127.0.0.1:8000"

async def test_rps(target_rps: int, duration: int = 15):
    """Test at specific RPS and return success rate."""
    success = 0
    fail = 0
    latencies = []
    
    connector = aiohttp.TCPConnector(limit=target_rps * 2, keepalive_timeout=30)
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
            
            # Cleanup done tasks
            pending = [t for t in pending if not t.done()]
            await asyncio.sleep(0.001)
        
        # Wait for remaining
        if pending:
            await asyncio.wait(pending, timeout=10)
    
    total = success + fail
    rate = (success / total * 100) if total > 0 else 0
    avg_lat = (sum(latencies) / len(latencies)) if latencies else 0
    elapsed = time.perf_counter() - start
    actual = total / elapsed if elapsed > 0 else 0
    
    print(f"Target: {target_rps:3d} RPS | Actual: {actual:5.1f} RPS | "
          f"Success: {rate:5.1f}% | Avg lat: {avg_lat:6.1f}ms | n={total}")
    
    return rate, actual, avg_lat

async def main():
    print("=" * 60)
    print("BACKEND CAPACITY CALIBRATION")
    print("=" * 60)
    print()
    
    results = []
    for rps in [5, 10, 15, 20, 25, 30]:
        rate, actual, lat = await test_rps(rps, duration=10)
        results.append((rps, rate, actual, lat))
        await asyncio.sleep(2)  # Cool down
    
    print()
    print("=" * 60)
    print("CAPACITY SUMMARY")
    print("=" * 60)
    
    # Find max RPS with >= 99% success
    max_stable_rps = 0
    for rps, rate, actual, lat in results:
        if rate >= 99.0:
            max_stable_rps = rps
    
    print(f"Max stable RPS (99%+ success): {max_stable_rps}")
    
    # Validate SLA
    print()
    print("SLA CHECK (target: 99.5% success):")
    for rps, rate, actual, lat in results:
        status = "PASS" if rate >= 99.5 else "FAIL"
        print(f"  [{status}] {rps} RPS: {rate:.1f}% success, {lat:.1f}ms avg")
    
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
