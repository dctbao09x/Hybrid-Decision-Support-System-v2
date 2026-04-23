# Makefile — Hybrid Decision Support System
# ==========================================
# GĐ8: Full Audit Automation Gate

.PHONY: help test lint audit clean

# Default Python interpreter
PYTHON ?= python

help:
	@echo "Available targets:"
	@echo "  make test    - Run all tests"
	@echo "  make lint    - Run linting"
	@echo "  make audit   - Run full governance audit (GĐ8)"
	@echo "  make clean   - Clean build artifacts"

# Run all tests
test:
	$(PYTHON) -m pytest tests/ -v --tb=short

# Run linting
lint:
	$(PYTHON) -m ruff check backend/ --fix

# GĐ8: Full governance audit
# Must PASS before merge
audit:
	$(PYTHON) scripts/audit/run_audit.py

# Clean build artifacts
clean:
	rm -rf __pycache__ .pytest_cache .coverage coverage.xml htmlcov/
	rm -rf audit_bundle.zip
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
