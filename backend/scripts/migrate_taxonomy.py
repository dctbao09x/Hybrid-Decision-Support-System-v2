"""
Migration helper for taxonomy refactor.

Outputs:
- Coverage report
- Legacy mapping validation
"""

import json
from pathlib import Path

from taxonomy.validate import startup_check, coverage_report, validate_legacy_mapping


def main() -> None:
    status = startup_check()
    coverage = coverage_report()
    mismatches = validate_legacy_mapping()

    output = {
        "status": status,
        "coverage": coverage,
        "legacy_mismatches": mismatches,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
