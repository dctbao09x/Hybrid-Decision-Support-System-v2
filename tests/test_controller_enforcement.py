# tests/test_controller_enforcement.py
"""
Controller Bypass Detection Tests
==================================

These tests ensure ALL router modules use ONLY controller.dispatch()
and do NOT directly import service classes.

Violations indicate architecture regression - routers MUST go through
the 8-step dispatch pipeline for:
1. Unified authentication
2. Consistent authorization  
3. Request validation
4. Context enrichment
5. Proper logging
6. XAI integration
7. Correlation tracking
8. Error handling

Run with: pytest tests/test_controller_enforcement.py -v
"""

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


# Forbidden direct imports - services that MUST be accessed via controller.dispatch()
FORBIDDEN_IMPORTS = {
    # Scoring service imports (HIGH SEVERITY)
    "backend.scoring.engine",
    "backend.scoring.service",
    "backend.scoring.ranking_engine",
    "backend.scoring.scoring_service",
    "backend.scoring.weight_optimizer",
    
    # Market service imports
    "backend.market.analyzer",
    "backend.market.signal_processor",
    
    # Inference service imports
    "backend.inference.engine",
    "backend.inference.service",
    
    # Feedback service imports (should go through controller)
    "backend.feedback.service",
}

# Forbidden class names in imports (e.g., "from x import RankingEngine")
FORBIDDEN_CLASSES = {
    "RankingEngine",
    "ScoringService",
    "WeightOptimizer",
    "ScoringEngine",
    "SignalProcessor",
    "InferenceEngine",
}

# Router files to check
ROUTER_PATTERNS = [
    "backend/api/routers/*.py",
    "backend/api/controllers/*.py",
]


def get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


def get_router_files() -> List[Path]:
    """Get all router files to check."""
    root = get_project_root()
    files = []
    
    for pattern in ROUTER_PATTERNS:
        files.extend(root.glob(pattern))
    
    # Filter out __init__.py, test files, and backup files
    return [f for f in files 
            if f.name != "__init__.py" 
            and not f.name.startswith("test_")
            and "_backup" not in f.name]


def extract_imports(filepath: Path) -> List[Tuple[int, str, str]]:
    """
    Extract all imports from a file.
    
    Returns:
        List of (line_number, import_type, import_path) tuples
    """
    imports = []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((node.lineno, "import", alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        imports.append((
                            node.lineno, 
                            "from", 
                            f"{node.module}.{alias.name}"
                        ))
    except SyntaxError:
        pass  # Skip files with syntax errors
    
    return imports


def check_forbidden_imports(filepath: Path) -> List[Dict]:
    """
    Check a file for forbidden direct imports.
    
    Returns:
        List of violations with line numbers and details
    """
    violations = []
    imports = extract_imports(filepath)
    
    for line_num, import_type, import_path in imports:
        # Check against forbidden module imports
        for forbidden in FORBIDDEN_IMPORTS:
            if import_path.startswith(forbidden):
                violations.append({
                    "file": str(filepath),
                    "line": line_num,
                    "type": import_type,
                    "import": import_path,
                    "reason": f"Direct import from forbidden module: {forbidden}",
                    "severity": "HIGH",
                    "fix": "Use controller.dispatch() instead"
                })
        
        # Check against forbidden class names
        for forbidden_class in FORBIDDEN_CLASSES:
            if import_path.endswith(f".{forbidden_class}"):
                violations.append({
                    "file": str(filepath),
                    "line": line_num,
                    "type": import_type,
                    "import": import_path,
                    "reason": f"Direct import of forbidden class: {forbidden_class}",
                    "severity": "HIGH",
                    "fix": "Use controller.dispatch() instead"
                })
    
    return violations


def check_direct_instantiation(filepath: Path) -> List[Dict]:
    """
    Check for direct instantiation of service classes.
    
    Detects patterns like:
        engine = RankingEngine()
        service = ScoringService(...)
    """
    violations = []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in FORBIDDEN_CLASSES:
                        violations.append({
                            "file": str(filepath),
                            "line": node.lineno,
                            "type": "instantiation",
                            "class": node.func.id,
                            "reason": f"Direct instantiation of {node.func.id}",
                            "severity": "HIGH",
                            "fix": "Use controller.dispatch() instead"
                        })
    except SyntaxError:
        pass
    
    return violations


class TestControllerEnforcement:
    """Test suite for controller enforcement."""
    
    def test_no_forbidden_imports_in_routers(self):
        """Ensure no router directly imports service modules."""
        router_files = get_router_files()
        all_violations = []
        
        for filepath in router_files:
            violations = check_forbidden_imports(filepath)
            all_violations.extend(violations)
        
        if all_violations:
            violation_report = "\n".join([
                f"  - {v['file']}:{v['line']} - {v['reason']}"
                for v in all_violations
            ])
            assert False, f"Controller bypass detected:\n{violation_report}"
    
    def test_no_direct_instantiation_in_routers(self):
        """Ensure no router directly instantiates service classes."""
        router_files = get_router_files()
        all_violations = []
        
        for filepath in router_files:
            violations = check_direct_instantiation(filepath)
            all_violations.extend(violations)
        
        if all_violations:
            violation_report = "\n".join([
                f"  - {v['file']}:{v['line']} - {v['reason']}"
                for v in all_violations
            ])
            assert False, f"Direct instantiation detected:\n{violation_report}"
    
    def test_scoring_router_uses_dispatch(self):
        """Verify scoring_router.py uses controller.dispatch() pattern."""
        root = get_project_root()
        scoring_router = root / "backend" / "api" / "routers" / "scoring_router.py"
        
        if not scoring_router.exists():
            return  # Skip if file doesn't exist
        
        with open(scoring_router, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that dispatch is used
        assert "controller.dispatch" in content, \
            "scoring_router.py must use controller.dispatch()"
        
        # Check no direct RankingEngine usage
        assert "RankingEngine(" not in content, \
            "scoring_router.py must not instantiate RankingEngine directly"
    
    def test_router_registry_completeness(self):
        """Verify all router files are registered in router_registry.py."""
        root = get_project_root()
        registry_path = root / "backend" / "api" / "router_registry.py"
        
        if not registry_path.exists():
            return
        
        with open(registry_path, "r", encoding="utf-8") as f:
            registry_content = f.read()
        
        # Check key routers are registered
        required_routers = [
            "scoring_router",
            "health_router",
            "ops_router",
            "killswitch_router",
        ]
        
        for router in required_routers:
            assert router in registry_content, \
                f"{router} must be registered in router_registry.py"


def run_enforcement_audit() -> Dict:
    """
    Run full enforcement audit and return report.
    
    Can be called from audit scripts.
    """
    router_files = get_router_files()
    
    report = {
        "status": "PASS",
        "files_checked": len(router_files),
        "violations": [],
        "summary": {}
    }
    
    for filepath in router_files:
        import_violations = check_forbidden_imports(filepath)
        instantiation_violations = check_direct_instantiation(filepath)
        
        report["violations"].extend(import_violations)
        report["violations"].extend(instantiation_violations)
    
    if report["violations"]:
        report["status"] = "FAIL"
        report["summary"]["high_severity"] = len([
            v for v in report["violations"] if v.get("severity") == "HIGH"
        ])
    
    return report


if __name__ == "__main__":
    # Run audit when executed directly
    import json
    report = run_enforcement_audit()
    print(json.dumps(report, indent=2))
