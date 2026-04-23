#!/usr/bin/env python
"""
Route Validation Test
=====================

Tests random endpoints to verify:
1. No 404 for expected routes
2. All workers return same routes
3. Routes are deterministically registered
"""

import asyncio
import random
import aiohttp
import sys
from collections import defaultdict

BASE_URL = "http://127.0.0.1:8000"

# Known good endpoints (should return 200 or auth error, not 404)
ENDPOINTS = [
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/api/v1/health/full"),
    ("GET", "/api/v1/health/startup"),
    ("GET", "/api/v1/health/startup/contract"),
    ("GET", "/api/v1/ops/status"),
    ("GET", "/api/v1/ops/sla"),
    ("GET", "/api/v1/crawlers/status"),
    ("GET", "/api/v1/kb/domains"),  # Correct KB endpoint
    ("GET", "/api/v1/feedback"),
    ("GET", "/api/v1/eval"),
    ("GET", "/api/v1/explain/stats"),
    ("GET", "/api/v1/rules"),
    ("GET", "/api/v1/taxonomy"),
    ("GET", "/api/v1/scoring"),
    ("GET", "/api/v1/mlops/models"),  # Correct MLOps endpoint
    ("GET", "/api/v1/governance/dashboard"),  # Correct governance endpoint
    ("GET", "/api/v1/resilience/bulkheads"),
    ("GET", "/api/v1/resilience/timeouts"),
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/metrics"),
]


async def test_route(session, method, path, results):
    """Test a single route."""
    try:
        async with session.request(method, f"{BASE_URL}{path}", timeout=aiohttp.ClientTimeout(total=5)) as response:
            status = response.status
            results["status_codes"][status] += 1
            
            if status == 404:
                results["404_routes"].append(f"{method} {path}")
                return False
            elif status in (200, 201):
                return True
            elif status in (401, 403):
                # Auth required but route exists
                return True
            elif status == 500:
                results["500_routes"].append(f"{method} {path}")
                return False
            else:
                return True
    except Exception as e:
        results["errors"].append(f"{method} {path}: {str(e)[:50]}")
        return False


async def stress_test_routes(total_requests=1000):
    """Stress test random endpoints."""
    results = {
        "status_codes": defaultdict(int),
        "404_routes": [],
        "500_routes": [],
        "errors": [],
    }
    
    async with aiohttp.ClientSession() as session:
        # Test all known endpoints first
        print(f"\n[1/2] Testing {len(ENDPOINTS)} known endpoints...")
        for method, path in ENDPOINTS:
            await test_route(session, method, path, results)
        
        # Report known endpoint status
        print(f"  Tested: {len(ENDPOINTS)}")
        if results["404_routes"]:
            print(f"  404 Not Found ({len(results['404_routes'])}):")
            for route in results["404_routes"]:
                print(f"    - {route}")
        
        # Reset for stress test
        initial_404 = results["404_routes"].copy()
        results["404_routes"] = []
        results["status_codes"] = defaultdict(int)
        
        # Stress test with random endpoints
        print(f"\n[2/2] Stress testing {total_requests} random requests...")
        
        tasks = []
        for _ in range(total_requests):
            method, path = random.choice(ENDPOINTS)
            tasks.append(test_route(session, method, path, results))
        
        await asyncio.gather(*tasks)
    
    return results, initial_404


async def main():
    print("=" * 60)
    print(" ROUTE VALIDATION TEST")
    print("=" * 60)
    
    # Check server is running
    print("\n[0/2] Checking server is running...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/") as response:
                if response.status != 200:
                    print(f"  ERROR: Server returned {response.status}")
                else:
                    print("  Server is running")
    except Exception as e:
        print(f"  ERROR: Cannot connect to server: {e}")
        sys.exit(1)
    
    results, initial_404 = await stress_test_routes(1000)
    
    # Summary
    print("\n" + "=" * 60)
    print(" VALIDATION SUMMARY")
    print("=" * 60)
    
    print("\nStatus Code Distribution:")
    for code, count in sorted(results["status_codes"].items()):
        print(f"  {code}: {count}")
    
    total_requests = sum(results["status_codes"].values())
    success_count = results["status_codes"].get(200, 0) + results["status_codes"].get(201, 0) + results["status_codes"].get(401, 0)
    error_404 = results["status_codes"].get(404, 0)
    error_500 = results["status_codes"].get(500, 0)
    
    print(f"\nTotal Requests: {total_requests}")
    print(f"Success/Auth: {success_count}")
    print(f"404 Errors: {error_404}")
    print(f"500 Errors: {error_500}")
    
    if initial_404:
        print(f"\n❌ INITIAL 404 ROUTES (not found):")
        for route in initial_404:
            print(f"  - {route}")
    
    if results["500_routes"]:
        print(f"\n⚠️  500 Error Routes:")
        for route in results["500_routes"][:10]:
            print(f"  - {route}")
    
    # Verdict
    print("\n" + "-" * 40)
    if error_404 == 0 and not initial_404:
        print("✅ VALIDATION PASSED: No 404 errors")
        print("   All routes are consistently registered")
        return 0
    else:
        print("❌ VALIDATION FAILED: Found 404 errors")
        print("   Routes may not be registered consistently")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
