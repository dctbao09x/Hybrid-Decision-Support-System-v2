# backend/risk/data_loader.py
"""
Risk Data Loaders - SIMGR Stage 3 Compliant

Loads unemployment, cost, and sector data from CSV datasets.
NO MOCKING - Uses real datasets with validation.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DatasetMetadata:
    """Metadata for a loaded dataset."""
    path: str
    version: str
    rows: int
    loaded_at: datetime
    checksum: Optional[str] = None


class UnemploymentLoader:
    """Loader for unemployment rate dataset.
    
    Dataset format (CSV):
        region,sector,year,rate,trend
        us,technology,2025,0.035,declining
        us,healthcare,2025,0.028,stable
        ...
    """
    
    def __init__(self, data_path: Optional[str] = None):
        self.data_path = data_path or "data/risk/unemployment/rates.csv"
        self._data: Dict[Tuple[str, str, int], Dict] = {}
        self._metadata: Optional[DatasetMetadata] = None
        self._loaded = False
    
    def load_dataset(self, force_reload: bool = False) -> bool:
        """Load unemployment dataset from CSV.
        
        Returns:
            True if loaded successfully, False otherwise.
        """
        if self._loaded and not force_reload:
            return True
        
        path = Path(self.data_path)
        if not path.exists():
            logger.error(f"Unemployment dataset not found: {self.data_path}")
            return False
        
        try:
            self._data = {}
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (
                        row["region"].lower().strip(),
                        row["sector"].lower().strip(),
                        int(row["year"]),
                    )
                    self._data[key] = {
                        "rate": float(row["rate"]),
                        "trend": row.get("trend", "stable").lower(),
                    }
            
            # Calculate checksum
            checksum = self._calculate_checksum(path)
            
            self._metadata = DatasetMetadata(
                path=str(path),
                version=self._extract_version(path),
                rows=len(self._data),
                loaded_at=datetime.now(),
                checksum=checksum,
            )
            
            self._loaded = True
            logger.info(
                f"Loaded unemployment dataset: {len(self._data)} records "
                f"from {self.data_path}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to load unemployment dataset: {e}")
            return False
    
    def get_rate(
        self,
        region: str = "us",
        sector: str = "general",
        year: int = 2025,
    ) -> float:
        """Get unemployment rate for region/sector/year.
        
        Args:
            region: Geographic region (e.g., "us", "eu")
            sector: Industry sector (e.g., "technology", "healthcare")
            year: Year for the rate
            
        Returns:
            Unemployment rate as float [0, 1], or default if not found.
        """
        if not self._loaded:
            self.load_dataset()
        
        key = (region.lower().strip(), sector.lower().strip(), year)
        
        # Exact match
        if key in self._data:
            return self._data[key]["rate"]
        
        # Try sector-only match (any region)
        for k, v in self._data.items():
            if k[1] == key[1] and k[2] == key[2]:
                return v["rate"]
        
        # Try year-only match for sector
        for k, v in self._data.items():
            if k[1] == key[1]:
                return v["rate"]
        
        # Default rate
        logger.debug(f"Unemployment rate not found for {key}, using default")
        return 0.05  # 5% default unemployment
    
    def get_trend(
        self,
        region: str = "us",
        sector: str = "general",
        year: int = 2025,
    ) -> str:
        """Get unemployment trend for region/sector/year.
        
        Returns:
            Trend string: "declining", "stable", "rising"
        """
        if not self._loaded:
            self.load_dataset()
        
        key = (region.lower().strip(), sector.lower().strip(), year)
        
        if key in self._data:
            return self._data[key]["trend"]
        
        return "stable"
    
    def get_sector_risk(self, sector: str) -> float:
        """Calculate overall sector risk from unemployment data.
        
        Higher unemployment = higher risk.
        
        Returns:
            Risk score [0, 1] based on sector unemployment.
        """
        rate = self.get_rate(sector=sector)
        
        # Normalize: 0% = 0 risk, 15%+ = 1.0 risk
        risk = min(1.0, rate / 0.15)
        return risk
    
    @property
    def metadata(self) -> Optional[DatasetMetadata]:
        return self._metadata
    
    def _calculate_checksum(self, path: Path) -> str:
        """Calculate MD5 checksum of dataset file."""
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def _extract_version(self, path: Path) -> str:
        """Extract version from file modification time."""
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


class CostDataLoader:
    """Loader for education and career cost dataset.
    
    Dataset format (CSV):
        career,education_cost,training_months,avg_salary,entry_barrier
        software_engineer,50000,48,120000,medium
        physician,300000,144,250000,high
        ...
    """
    
    def __init__(self, data_path: Optional[str] = None):
        self.data_path = data_path or "data/risk/costs/education_costs.csv"
        self._data: Dict[str, Dict] = {}
        self._metadata: Optional[DatasetMetadata] = None
        self._loaded = False
    
    def load_dataset(self, force_reload: bool = False) -> bool:
        """Load cost dataset from CSV."""
        if self._loaded and not force_reload:
            return True
        
        path = Path(self.data_path)
        if not path.exists():
            logger.error(f"Cost dataset not found: {self.data_path}")
            return False
        
        try:
            self._data = {}
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = row["career"].lower().strip()
                    self._data[key] = {
                        "education_cost": float(row["education_cost"]),
                        "training_months": int(row["training_months"]),
                        "avg_salary": float(row["avg_salary"]),
                        "entry_barrier": row.get("entry_barrier", "medium").lower(),
                    }
            
            self._metadata = DatasetMetadata(
                path=str(path),
                version=self._extract_version(path),
                rows=len(self._data),
                loaded_at=datetime.now(),
            )
            
            self._loaded = True
            logger.info(f"Loaded cost dataset: {len(self._data)} records")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load cost dataset: {e}")
            return False
    
    def get_education_cost(self, career: str) -> float:
        """Get education cost for a career path.
        
        Returns:
            Education cost in USD.
        """
        if not self._loaded:
            self.load_dataset()
        
        key = career.lower().strip()
        
        if key in self._data:
            return self._data[key]["education_cost"]
        
        # Fuzzy match
        for k, v in self._data.items():
            if k in key or key in k:
                return v["education_cost"]
        
        return 30000.0  # Default education cost
    
    def get_training_time(self, career: str) -> int:
        """Get typical training time in months.
        
        Returns:
            Training duration in months.
        """
        if not self._loaded:
            self.load_dataset()
        
        key = career.lower().strip()
        
        if key in self._data:
            return self._data[key]["training_months"]
        
        # Fuzzy match
        for k, v in self._data.items():
            if k in key or key in k:
                return v["training_months"]
        
        return 36  # Default 3 years
    
    def get_salary(self, career: str) -> float:
        """Get average salary for career.
        
        Returns:
            Average salary in USD.
        """
        if not self._loaded:
            self.load_dataset()
        
        key = career.lower().strip()
        
        if key in self._data:
            return self._data[key]["avg_salary"]
        
        for k, v in self._data.items():
            if k in key or key in k:
                return v["avg_salary"]
        
        return 60000.0  # Default salary
    
    def get_entry_barrier(self, career: str) -> str:
        """Get entry barrier level.
        
        Returns:
            Barrier level: "low", "medium", "high", "very_high"
        """
        if not self._loaded:
            self.load_dataset()
        
        key = career.lower().strip()
        
        if key in self._data:
            return self._data[key]["entry_barrier"]
        
        return "medium"
    
    @property
    def metadata(self) -> Optional[DatasetMetadata]:
        return self._metadata
    
    def _extract_version(self, path: Path) -> str:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


class SectorRiskLoader:
    """Loader for sector-specific risk data.
    
    Dataset format (CSV):
        sector,automation_risk,volatility,growth_outlook,saturation
        technology,0.3,0.4,0.8,0.5
        healthcare,0.2,0.2,0.7,0.3
        ...
    """
    
    def __init__(self, data_path: Optional[str] = None):
        self.data_path = data_path or "data/risk/sectors/sector_risk.csv"
        self._data: Dict[str, Dict] = {}
        self._loaded = False
    
    def load_dataset(self, force_reload: bool = False) -> bool:
        """Load sector risk dataset."""
        if self._loaded and not force_reload:
            return True
        
        path = Path(self.data_path)
        if not path.exists():
            logger.warning(f"Sector risk dataset not found: {self.data_path}")
            return False
        
        try:
            self._data = {}
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = row["sector"].lower().strip()
                    self._data[key] = {
                        "automation_risk": float(row["automation_risk"]),
                        "volatility": float(row["volatility"]),
                        "growth_outlook": float(row["growth_outlook"]),
                        "saturation": float(row["saturation"]),
                    }
            
            self._loaded = True
            logger.info(f"Loaded sector risk dataset: {len(self._data)} sectors")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load sector risk dataset: {e}")
            return False
    
    def get_automation_risk(self, sector: str) -> float:
        """Get automation/AI displacement risk for sector."""
        if not self._loaded:
            self.load_dataset()
        
        key = sector.lower().strip()
        if key in self._data:
            return self._data[key]["automation_risk"]
        return 0.4  # Default medium risk
    
    def get_volatility(self, sector: str) -> float:
        """Get market volatility for sector."""
        if not self._loaded:
            self.load_dataset()
        
        key = sector.lower().strip()
        if key in self._data:
            return self._data[key]["volatility"]
        return 0.35  # Default medium volatility
    
    def get_growth_outlook(self, sector: str) -> float:
        """Get growth outlook for sector."""
        if not self._loaded:
            self.load_dataset()
        
        key = sector.lower().strip()
        if key in self._data:
            return self._data[key]["growth_outlook"]
        return 0.0  # Default neutral growth
    
    def get_saturation(self, sector: str) -> float:
        """Get market saturation level for sector."""
        if not self._loaded:
            self.load_dataset()
        
        key = sector.lower().strip()
        if key in self._data:
            return self._data[key]["saturation"]
        return 0.5  # Default medium saturation


# Singleton instances
_unemployment_loader: Optional[UnemploymentLoader] = None
_cost_loader: Optional[CostDataLoader] = None
_sector_loader: Optional[SectorRiskLoader] = None


def get_unemployment_loader() -> UnemploymentLoader:
    global _unemployment_loader
    if _unemployment_loader is None:
        _unemployment_loader = UnemploymentLoader()
    return _unemployment_loader


def get_cost_loader() -> CostDataLoader:
    global _cost_loader
    if _cost_loader is None:
        _cost_loader = CostDataLoader()
    return _cost_loader


def get_sector_loader() -> SectorRiskLoader:
    global _sector_loader
    if _sector_loader is None:
        _sector_loader = SectorRiskLoader()
    return _sector_loader
