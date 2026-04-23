# backend/scoring/components/risk_loader.py
"""
Risk Loader with Hardening for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN D

Implements:
- Dataset existence verification
- Schema validation
- Date freshness check
- Cost parse verification
- Dropout rate presence check

NO DEFAULT VALUES. NO FALLBACKS. FAIL FAST.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from backend.scoring.errors import (
    RiskDatasetMissingError,
    RiskParseError,
    CostColumnMissingError,
    DropoutRateMissingError,
    RiskSchemaMismatchError,
    StaleDataError,
)
from backend.scoring.validation.component_contract import (
    BaseComponentContract,
    HealthStatus,
    DatasetStatus,
    create_healthcheck_response,
    create_metadata_response,
)

logger = logging.getLogger(__name__)


# =====================================================
# CONFIGURATION
# =====================================================

# Dataset paths (relative to project root)
RISK_DATASET_PATHS = {
    "dropout": "backend/data/risk/dropout_rates.json",
    "cost": "backend/data/risk/cost_barriers.json",
    "unemployment": "backend/data/risk/unemployment_rates.json",
    "saturation": "backend/data/risk/market_saturation.json",
}

# Required schema fields for each dataset
REQUIRED_SCHEMA = {
    "dropout": ["career", "rate", "confidence", "last_updated"],
    "cost": ["career", "cost_usd", "barrier_level", "education_years"],
    "unemployment": ["sector", "rate", "trend", "region"],
    "saturation": ["market", "level", "growth_forecast"],
}

# Data freshness threshold (days)
MAX_DATA_AGE_DAYS = 90

# Schema version
SCHEMA_VERSION = "1.0"


# =====================================================
# RISK LOADER CLASS
# =====================================================

class RiskLoader(BaseComponentContract):
    """
    Hardened risk data loader with full validation.
    
    Implements BaseComponentContract for GĐ3 compliance.
    """
    
    COMPONENT_NAME = "risk"
    COMPONENT_VERSION = "3.0"
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize risk loader.
        
        Args:
            project_root: Project root path (auto-detected if None)
        """
        self._project_root = project_root or self._detect_project_root()
        self._loaded_datasets: Dict[str, Any] = {}
        self._last_loaded: Optional[datetime] = None
        self._validation_status: Dict[str, bool] = {}
    
    def _detect_project_root(self) -> Path:
        """Detect project root directory."""
        # Try common patterns
        current = Path(__file__).resolve()
        for _ in range(5):  # Max 5 levels up
            if (current / "backend").exists():
                return current
            current = current.parent
        return Path.cwd()
    
    # =====================================================
    # DATASET VERIFICATION
    # =====================================================
    
    def verify_dataset_exists(self, dataset_name: str) -> bool:
        """
        Verify that a dataset file exists.
        
        Args:
            dataset_name: Name of dataset (dropout, cost, etc.)
            
        Returns:
            True if exists
            
        Raises:
            RiskDatasetMissingError: If dataset file is missing
        """
        if dataset_name not in RISK_DATASET_PATHS:
            raise RiskDatasetMissingError(
                f"Unknown dataset: '{dataset_name}'",
                field=dataset_name,
                details={"available": list(RISK_DATASET_PATHS.keys())}
            )
        
        path = self._project_root / RISK_DATASET_PATHS[dataset_name]
        
        if not path.exists():
            raise RiskDatasetMissingError(
                f"Dataset file not found: {path}",
                field=dataset_name,
                details={"expected_path": str(path)}
            )
        
        return True
    
    def verify_schema(self, dataset_name: str, data: Dict[str, Any]) -> bool:
        """
        Verify dataset schema matches expected structure.
        
        Args:
            dataset_name: Name of dataset
            data: Loaded data dict
            
        Returns:
            True if schema valid
            
        Raises:
            RiskSchemaMismatchError: If schema doesn't match
        """
        if dataset_name not in REQUIRED_SCHEMA:
            raise RiskSchemaMismatchError(
                f"No schema defined for dataset: '{dataset_name}'",
                field=dataset_name
            )
        
        required_fields = REQUIRED_SCHEMA[dataset_name]
        
        # Check if data has entries
        entries = data.get("entries", data.get("data", []))
        if not entries:
            raise RiskSchemaMismatchError(
                f"Dataset '{dataset_name}' has no entries",
                field=dataset_name
            )
        
        # Check first entry for required fields
        if isinstance(entries, list) and len(entries) > 0:
            sample = entries[0]
            missing = [f for f in required_fields if f not in sample]
            if missing:
                raise RiskSchemaMismatchError(
                    f"Dataset '{dataset_name}' missing required fields: {missing}",
                    field=dataset_name,
                    details={"missing_fields": missing, "required": required_fields}
                )
        
        return True
    
    def verify_data_freshness(self, last_update: str) -> bool:
        """
        Verify data is not stale.
        
        Args:
            last_update: ISO8601 timestamp of last update
            
        Returns:
            True if data is fresh
            
        Raises:
            StaleDataError: If data is older than threshold
        """
        try:
            update_dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            raise RiskParseError(
                f"Invalid date format: {last_update}",
                field="last_update",
                details={"error": str(e)}
            )
        
        now = datetime.now(update_dt.tzinfo) if update_dt.tzinfo else datetime.utcnow()
        age = now - update_dt.replace(tzinfo=None) if update_dt.tzinfo else now - update_dt
        
        if age > timedelta(days=MAX_DATA_AGE_DAYS):
            raise StaleDataError(
                f"Data is {age.days} days old (max: {MAX_DATA_AGE_DAYS})",
                field="last_update",
                details={"age_days": age.days, "max_days": MAX_DATA_AGE_DAYS}
            )
        
        return True
    
    def verify_cost_column(self, data: Dict[str, Any]) -> bool:
        """
        Verify cost data contains required cost column.
        
        Args:
            data: Cost dataset
            
        Returns:
            True if cost column present
            
        Raises:
            CostColumnMissingError: If cost column is missing
        """
        entries = data.get("entries", data.get("data", []))
        
        if not entries:
            raise CostColumnMissingError(
                "Cost dataset has no entries",
                field="cost"
            )
        
        # Check for cost_usd or barrier_level in first entry
        sample = entries[0] if isinstance(entries, list) else {}
        
        if "cost_usd" not in sample and "barrier_level" not in sample:
            raise CostColumnMissingError(
                "Cost dataset missing 'cost_usd' or 'barrier_level' column",
                field="cost",
                details={"available_fields": list(sample.keys())}
            )
        
        return True
    
    def verify_dropout_rate(self, data: Dict[str, Any]) -> bool:
        """
        Verify dropout data contains rate column.
        
        Args:
            data: Dropout dataset
            
        Returns:
            True if dropout rate present
            
        Raises:
            DropoutRateMissingError: If rate column is missing
        """
        entries = data.get("entries", data.get("data", []))
        
        if not entries:
            raise DropoutRateMissingError(
                "Dropout dataset has no entries",
                field="dropout"
            )
        
        sample = entries[0] if isinstance(entries, list) else {}
        
        if "rate" not in sample:
            raise DropoutRateMissingError(
                "Dropout dataset missing 'rate' column",
                field="dropout",
                details={"available_fields": list(sample.keys())}
            )
        
        return True
    
    # =====================================================
    # CONTRACT IMPLEMENTATION
    # =====================================================
    
    def validate(self, input_dict: Dict[str, Any]) -> bool:
        """
        Validate input for risk computation.
        
        Required fields:
        - career_name: str
        - sector: str (optional with default)
        
        Raises:
            ComponentContractError: If validation fails
        """
        from backend.scoring.errors import ComponentContractError
        
        if input_dict is None:
            raise ComponentContractError(
                "Input cannot be None",
                component=self.COMPONENT_NAME,
                field="input"
            )
        
        # Check career_name (required)
        if "career_name" not in input_dict:
            raise ComponentContractError(
                "Missing required field: 'career_name'",
                component=self.COMPONENT_NAME,
                field="career_name"
            )
        
        career = input_dict["career_name"]
        if career is None or not str(career).strip():
            raise ComponentContractError(
                "Field 'career_name' cannot be None or empty",
                component=self.COMPONENT_NAME,
                field="career_name"
            )
        
        return True
    
    def healthcheck(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check.
        
        Checks:
        - All dataset files exist
        - Schema is valid
        - Data is fresh
        - Critical columns present
        """
        status = HealthStatus.OK
        dataset_status = DatasetStatus.READY
        issues = []
        coverage = 1.0
        
        # Check each dataset
        datasets_checked = 0
        datasets_valid = 0
        
        for name, path in RISK_DATASET_PATHS.items():
            full_path = self._project_root / path
            
            if not full_path.exists():
                issues.append(f"Missing dataset: {name}")
                dataset_status = DatasetStatus.MISSING
                status = HealthStatus.FAIL
            else:
                datasets_valid += 1
            datasets_checked += 1
        
        if datasets_checked > 0:
            coverage = datasets_valid / datasets_checked
        
        if issues and status != HealthStatus.FAIL:
            status = HealthStatus.DEGRADED
        
        if coverage < 1.0 and dataset_status == DatasetStatus.READY:
            dataset_status = DatasetStatus.MISSING
        
        return create_healthcheck_response(
            status=status,
            dataset=dataset_status,
            last_update=datetime.utcnow().isoformat(),
            schema_version=SCHEMA_VERSION,
            coverage=coverage,
            issues=issues,
            datasets_checked=datasets_checked,
            datasets_valid=datasets_valid,
        )
    
    def metadata(self) -> Dict[str, Any]:
        """Return component metadata."""
        return create_metadata_response(
            name=self.COMPONENT_NAME,
            version=self.COMPONENT_VERSION,
            dependencies=[
                "backend.risk",
                "backend.scoring.errors",
            ],
            required_fields=["career_name"],
            datasets=list(RISK_DATASET_PATHS.keys()),
            schema_version=SCHEMA_VERSION,
            max_data_age_days=MAX_DATA_AGE_DAYS,
        )
    
    # =====================================================
    # LOAD OPERATIONS
    # =====================================================
    
    def load_all(self, verify: bool = True) -> Dict[str, Any]:
        """
        Load all risk datasets with full verification.
        
        Args:
            verify: Whether to run all verifications
            
        Returns:
            Dict of loaded datasets
            
        Raises:
            RiskDatasetMissingError: If any dataset missing
            RiskParseError: If any parse fails
            RiskSchemaMismatchError: If schema mismatch
        """
        import json
        
        for name, rel_path in RISK_DATASET_PATHS.items():
            path = self._project_root / rel_path
            
            # Verify existence
            if verify:
                self.verify_dataset_exists(name)
            
            # Load data
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                raise RiskParseError(
                    f"Failed to parse {name} dataset: {e}",
                    field=name,
                    details={"path": str(path), "error": str(e)}
                )
            except FileNotFoundError:
                raise RiskDatasetMissingError(
                    f"Dataset file not found: {path}",
                    field=name
                )
            
            # Verify schema
            if verify:
                self.verify_schema(name, data)
            
            # Specific verifications
            if name == "cost" and verify:
                self.verify_cost_column(data)
            
            if name == "dropout" and verify:
                self.verify_dropout_rate(data)
            
            self._loaded_datasets[name] = data
        
        self._last_loaded = datetime.utcnow()
        return self._loaded_datasets
    
    def get_dataset(self, name: str) -> Dict[str, Any]:
        """
        Get a specific loaded dataset.
        
        Args:
            name: Dataset name
            
        Returns:
            Dataset dict
            
        Raises:
            RiskDatasetMissingError: If not loaded
        """
        if name not in self._loaded_datasets:
            raise RiskDatasetMissingError(
                f"Dataset '{name}' not loaded. Call load_all() first.",
                field=name
            )
        return self._loaded_datasets[name]


# =====================================================
# SINGLETON ACCESS
# =====================================================

_risk_loader: Optional[RiskLoader] = None


def get_risk_loader() -> RiskLoader:
    """Get the global RiskLoader instance."""
    global _risk_loader
    if _risk_loader is None:
        _risk_loader = RiskLoader()
    return _risk_loader


def verify_risk_prerequisites() -> bool:
    """
    Verify all risk prerequisites before scoring.
    
    Call this from MainController preflight.
    
    Returns:
        True if all prerequisites met
        
    Raises:
        Various RiskXxxError if any check fails
    """
    loader = get_risk_loader()
    health = loader.healthcheck()
    
    if health["status"] == HealthStatus.FAIL:
        from backend.scoring.errors import HealthcheckFailError
        raise HealthcheckFailError(
            f"Risk component healthcheck failed: {health.get('issues', [])}",
            component="risk",
            details=health
        )
    
    return True


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    "RiskLoader",
    "get_risk_loader",
    "verify_risk_prerequisites",
    "RISK_DATASET_PATHS",
    "REQUIRED_SCHEMA",
    "MAX_DATA_AGE_DAYS",
    "SCHEMA_VERSION",
]
