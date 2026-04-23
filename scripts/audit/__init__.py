# scripts/audit/__init__.py
"""
GĐ8 Audit Automation Package

Zero-manual governance verification system.
"""

from scripts.audit.run_audit import AuditRunner, main

__all__ = ["AuditRunner", "main"]
