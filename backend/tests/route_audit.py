#!/usr/bin/env python
"""
Route Consistency Audit Script
==============================

Dumps all registered routes from the FastAPI app and detects:
1. Missing routes
2. Duplicate routes
3. Prefix mismatches
4. Worker inconsistencies

Usage:
    python -m backend.tests.route_audit
"""

import sys
import os
import json
import hashlib
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Any

# Setup path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENVIRONMENT", "development")


def get_route_signature(route) -> str:
    """Generate unique signature for a route."""
    methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
    return f"{methods}:{route.path}"


def dump_routes_from_app(app) -> Dict[str, Any]:
    """Extract all routes from a FastAPI app."""
    routes = []
    route_set = set()
    duplicates = []
    
    for route in app.routes:
        # Skip built-in routes
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            sig = get_route_signature(route)
            
            route_info = {
                "path": route.path,
                "methods": sorted(list(route.methods - {"HEAD", "OPTIONS"})),
                "name": route.name if hasattr(route, 'name') else None,
                "endpoint": route.endpoint.__name__ if hasattr(route, 'endpoint') else None,
            }
            
            if sig in route_set:
                duplicates.append(route_info)
            else:
                route_set.add(sig)
                routes.append(route_info)
    
    # Sort by path
    routes.sort(key=lambda x: x["path"])
    
    # Generate hash for comparison
    route_hash = hashlib.md5(
        json.dumps([r["path"] for r in routes], sort_keys=True).encode()
    ).hexdigest()[:12]
    
    return {
        "route_count": len(routes),
        "routes": routes,
        "duplicates": duplicates,
        "hash": route_hash,
    }


def analyze_routes(route_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze route patterns for issues."""
    issues = []
    warnings = []
    routes = route_data["routes"]
    
    # Check for prefix consistency
    api_v1_routes = [r for r in routes if r["path"].startswith("/api/v1/")]
    legacy_routes = [r for r in routes if not r["path"].startswith("/api/v1/") and r["path"] != "/"]
    
    if legacy_routes:
        warnings.append({
            "type": "legacy_routes",
            "message": f"Found {len(legacy_routes)} routes outside /api/v1 prefix",
            "routes": [r["path"] for r in legacy_routes],
        })
    
    # Check for double prefix
    double_prefix = [r for r in routes if "/api/v1/api/v1" in r["path"]]
    if double_prefix:
        issues.append({
            "type": "double_prefix",
            "message": "Routes with double /api/v1 prefix detected",
            "routes": [r["path"] for r in double_prefix],
        })
    
    # Check for duplicates
    if route_data["duplicates"]:
        issues.append({
            "type": "duplicates",
            "message": f"Found {len(route_data['duplicates'])} duplicate route registrations",
            "routes": [r["path"] for r in route_data["duplicates"]],
        })
    
    # Group routes by prefix
    prefix_groups = defaultdict(list)
    for route in routes:
        parts = route["path"].split("/")
        if len(parts) >= 4:
            prefix = "/".join(parts[:4])
            prefix_groups[prefix].append(route["path"])
    
    return {
        "issues": issues,
        "warnings": warnings,
        "prefix_groups": dict(prefix_groups),
        "api_v1_count": len(api_v1_routes),
        "legacy_count": len(legacy_routes),
    }


def compare_entrypoints() -> Dict[str, Any]:
    """Compare routes between run_api.py and main.py entrypoints."""
    results = {}
    
    # Test run_api.py (production entrypoint)
    print("Loading run_api.py entrypoint...")
    try:
        from backend.run_api import app as run_api_app
        run_api_routes = dump_routes_from_app(run_api_app)
        results["run_api"] = {
            "status": "loaded",
            **run_api_routes,
            "analysis": analyze_routes(run_api_routes),
        }
        print(f"  Routes: {run_api_routes['route_count']}, Hash: {run_api_routes['hash']}")
    except Exception as e:
        results["run_api"] = {"status": "error", "error": str(e)}
        print(f"  ERROR: {e}")
    
    # Test main.py (legacy entrypoint)
    print("\nLoading main.py entrypoint...")
    try:
        from backend.main import app as main_app
        main_routes = dump_routes_from_app(main_app)
        results["main"] = {
            "status": "loaded",
            **main_routes,
            "analysis": analyze_routes(main_routes),
        }
        print(f"  Routes: {main_routes['route_count']}, Hash: {main_routes['hash']}")
    except Exception as e:
        results["main"] = {"status": "error", "error": str(e)}
        print(f"  ERROR: {e}")
    
    # Compare if both loaded
    if results.get("run_api", {}).get("status") == "loaded" and results.get("main", {}).get("status") == "loaded":
        run_api_paths = set(r["path"] for r in results["run_api"]["routes"])
        main_paths = set(r["path"] for r in results["main"]["routes"])
        
        results["comparison"] = {
            "run_api_only": sorted(list(run_api_paths - main_paths)),
            "main_only": sorted(list(main_paths - run_api_paths)),
            "common": len(run_api_paths & main_paths),
            "hash_match": results["run_api"]["hash"] == results["main"]["hash"],
        }
        
        print("\n=== ROUTE COMPARISON ===")
        print(f"run_api.py routes: {len(run_api_paths)}")
        print(f"main.py routes: {len(main_paths)}")
        print(f"Common routes: {results['comparison']['common']}")
        print(f"Hash match: {results['comparison']['hash_match']}")
        
        if results["comparison"]["run_api_only"]:
            print(f"\nOnly in run_api.py ({len(results['comparison']['run_api_only'])} routes):")
            for path in results["comparison"]["run_api_only"][:10]:
                print(f"  + {path}")
            if len(results["comparison"]["run_api_only"]) > 10:
                print(f"  ... and {len(results['comparison']['run_api_only']) - 10} more")
        
        if results["comparison"]["main_only"]:
            print(f"\nOnly in main.py ({len(results['comparison']['main_only'])} routes):")
            for path in results["comparison"]["main_only"][:10]:
                print(f"  - {path}")
            if len(results["comparison"]["main_only"]) > 10:
                print(f"  ... and {len(results['comparison']['main_only']) - 10} more")
    
    return results


def check_conditional_imports() -> Dict[str, Any]:
    """Scan for conditional router imports that could cause inconsistency."""
    import ast
    
    issues = []
    files_checked = []
    
    target_files = [
        PROJECT_ROOT / "backend" / "run_api.py",
        PROJECT_ROOT / "backend" / "main.py",
        PROJECT_ROOT / "backend" / "inference" / "api_server_v2.py",
    ]
    
    for filepath in target_files:
        if not filepath.exists():
            continue
        
        files_checked.append(str(filepath.relative_to(PROJECT_ROOT)))
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        
        # Find try/except blocks containing include_router
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                # Check if try block contains include_router
                has_include_router = False
                imports_in_try = []
                
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if hasattr(child, 'func') and hasattr(child.func, 'attr'):
                            if child.func.attr == 'include_router':
                                has_include_router = True
                    if isinstance(child, ast.Import):
                        for alias in child.names:
                            imports_in_try.append(alias.name)
                    if isinstance(child, ast.ImportFrom):
                        imports_in_try.append(child.module or "")
                
                if has_include_router and imports_in_try:
                    issues.append({
                        "file": str(filepath.relative_to(PROJECT_ROOT)),
                        "line": node.lineno,
                        "type": "conditional_router_import",
                        "imports": imports_in_try,
                        "impact": "Router may not be registered if import fails",
                    })
    
    return {
        "files_checked": files_checked,
        "issues": issues,
    }


def print_route_table(routes: List[Dict], title: str = "Routes"):
    """Print routes in a formatted table."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")
    print(f"{'Methods':<15} {'Path':<45}")
    print(f"{'-'*15} {'-'*45}")
    
    for route in routes:
        methods = ",".join(route["methods"])
        print(f"{methods:<15} {route['path']:<45}")


def main():
    print("=" * 60)
    print(" ROUTE CONSISTENCY AUDIT")
    print("=" * 60)
    
    # 1. Compare entrypoints
    print("\n[1/3] Comparing entrypoint routes...")
    comparison = compare_entrypoints()
    
    # 2. Check for conditional imports
    print("\n[2/3] Scanning for conditional router imports...")
    import_analysis = check_conditional_imports()
    
    if import_analysis["issues"]:
        print(f"\n⚠️  Found {len(import_analysis['issues'])} conditional import issues:")
        for issue in import_analysis["issues"]:
            print(f"  File: {issue['file']}:{issue['line']}")
            print(f"  Type: {issue['type']}")
            print(f"  Impact: {issue['impact']}")
            print()
    
    # 3. Generate report
    print("\n[3/3] Generating audit report...")
    
    report = {
        "entrypoint_comparison": comparison,
        "conditional_imports": import_analysis,
    }
    
    # Save report
    report_path = PROJECT_ROOT / "ROUTE_AUDIT_REPORT.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved to: {report_path}")
    
    # Summary
    print("\n" + "=" * 60)
    print(" AUDIT SUMMARY")
    print("=" * 60)
    
    issues_found = 0
    
    if comparison.get("run_api", {}).get("analysis", {}).get("issues"):
        issues_found += len(comparison["run_api"]["analysis"]["issues"])
        print("\n❌ run_api.py issues:")
        for issue in comparison["run_api"]["analysis"]["issues"]:
            print(f"  - {issue['type']}: {issue['message']}")
    
    if comparison.get("main", {}).get("analysis", {}).get("issues"):
        issues_found += len(comparison["main"]["analysis"]["issues"])
        print("\n❌ main.py issues:")
        for issue in comparison["main"]["analysis"]["issues"]:
            print(f"  - {issue['type']}: {issue['message']}")
    
    issues_found += len(import_analysis["issues"])
    
    if comparison.get("comparison", {}).get("run_api_only"):
        print(f"\n⚠️  {len(comparison['comparison']['run_api_only'])} routes only in run_api.py")
    
    if comparison.get("comparison", {}).get("main_only"):
        print(f"\n⚠️  {len(comparison['comparison']['main_only'])} routes only in main.py")
    
    if issues_found == 0:
        print("\n✅ No critical issues found")
    else:
        print(f"\n❌ Total issues: {issues_found}")
    
    return report


if __name__ == "__main__":
    main()
