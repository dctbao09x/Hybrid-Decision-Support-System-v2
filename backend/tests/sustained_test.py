#!/usr/bin/env python3
"""Sustained load test with CPU/memory monitoring."""
import asyncio
import time
import aiohttp
import psutil

BASE_URL = "http://127.0.0.1:8000"
TARGET_RPS = 100
DURATION = 60


async def sustained_test():
    results = {"success": 0, "fail": 0, "latencies": []}
    cpu_samples = []
    mem_samples = []
    
    connector = aiohttp.TCPConnector(limit=300, limit_per_host=300, keepalive_timeout=30)
    timeout = aiohttp.ClientTimeout(total=10)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start = time.perf_counter()
        end = start + DURATION
        interval = 1.0 / TARGET_RPS
        next_t = start
        pending = []
        sample_t = start
        
        async def req():
            t0 = time.perf_counter()
            try:
                async with session.get(f"{BASE_URL}/api/v1/health") as r:
                    lat = (time.perf_counter() - t0) * 1000
                    if r.status == 200:
                        results["success"] += 1
                        results["latencies"].append(lat)
                    else:
                        results["fail"] += 1
            except:
                results["fail"] += 1
        
        while time.perf_counter() < end:
            now = time.perf_counter()
            while next_t <= now and next_t < end:
                pending.append(asyncio.create_task(req()))
                next_t += interval
            pending = [t for t in pending if not t.done()]
            
            # Sample CPU/memory every 5 seconds
            if now - sample_t >= 5:
                cpu_samples.append(psutil.cpu_percent())
                mem_samples.append(psutil.virtual_memory().percent)
                sample_t = now
                elapsed = int(now - start)
                current_rps = results["success"] / elapsed if elapsed > 0 else 0
                print(f"  Progress: {elapsed}s | RPS: {current_rps:.1f} | CPU: {cpu_samples[-1]:.0f}% | Mem: {mem_samples[-1]:.0f}%")
            
            await asyncio.sleep(0.001)
        
        if pending:
            await asyncio.wait(pending, timeout=10)
    
    elapsed = time.perf_counter() - start
    total = results["success"] + results["fail"]
    rate = results["success"] / total * 100 if total > 0 else 0
    actual_rps = total / elapsed if elapsed > 0 else 0
    lat = sorted(results["latencies"])
    n = len(lat)
    
    print()
    print("=" * 60)
    print("SUSTAINED TEST RESULTS (100 RPS x 60s)")
    print("=" * 60)
    print(f"Total Requests: {total}")
    print(f"Successful: {results['success']}")
    print(f"Failed: {results['fail']}")
    print(f"Success Rate: {rate:.2f}%")
    print(f"Actual RPS: {actual_rps:.1f}")
    print()
    print("Latency (ms):")
    print(f"  Min: {lat[0]:.1f}")
    print(f"  Avg: {sum(lat)/n:.1f}")
    print(f"  P50: {lat[int(n*0.50)]:.1f}")
    print(f"  P95: {lat[int(n*0.95)]:.1f}")
    print(f"  P99: {lat[int(n*0.99)]:.1f}")
    print(f"  Max: {lat[-1]:.1f}")
    print()
    print("System:")
    print(f"  Avg CPU: {sum(cpu_samples)/len(cpu_samples):.1f}%")
    print(f"  Avg Mem: {sum(mem_samples)/len(mem_samples):.1f}%")
    print("=" * 60)
    
    sla_pass = rate >= 99.5 and lat[int(n*0.95)] <= 100
    print(f"SLA VERDICT: {'PASS' if sla_pass else 'FAIL'}")
    print("=" * 60)
    
    return sla_pass


if __name__ == "__main__":
    print("=" * 60)
    print("SUSTAINED LOAD TEST: 100 RPS for 60 seconds")
    print("=" * 60)
    result = asyncio.run(sustained_test())
    exit(0 if result else 1)
