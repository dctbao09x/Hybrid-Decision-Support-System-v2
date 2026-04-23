#!/usr/bin/env python
"""
OpenAPI Route Extractor
======================

Dumps all routes from OpenAPI spec.
"""
import json
import urllib.request

url = "http://127.0.0.1:8000/openapi.json"

with urllib.request.urlopen(url) as response:
    openapi = json.load(response)

# Extract all paths
paths = list(openapi.get("paths", {}).keys())

# Group by prefix
from collections import defaultdict
prefix_groups = defaultdict(list)
for path in paths:
    parts = path.split("/")
    if len(parts) >= 4:
        prefix = "/".join(parts[:4])
        prefix_groups[prefix].append(path)
    else:
        prefix_groups[path].append(path)

print(f"Total routes: {len(paths)}")
print("\nBy prefix:")
for prefix, routes in sorted(prefix_groups.items()):
    print(f"  {prefix}: {len(routes)} routes")

# Check for specific routes
kb_routes = [p for p in paths if "/kb" in p]
mlops_routes = [p for p in paths if "/mlops" in p]
gov_routes = [p for p in paths if "/governance" in p]

print(f"\nKB routes ({len(kb_routes)}):")
for r in kb_routes[:5]:
    print(f"  {r}")

print(f"\nMLOps routes ({len(mlops_routes)}):")
for r in mlops_routes[:5]:
    print(f"  {r}")

print(f"\nGovernance routes ({len(gov_routes)}):")
for r in gov_routes[:5]:
    print(f"  {r}")
