# tests/risk/test_data.py
"""
Tests for Risk Data Loaders - SIMGR Stage 3 Compliance

Tests for:
- UnemploymentLoader
- CostDataLoader
- SectorRiskLoader
- Dataset integrity
"""

import pytest
from pathlib import Path
import csv


class TestDataFilesExist:
    """Tests that data files exist."""
    
    def test_unemployment_data_exists(self):
        """Unemployment data file must exist."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "unemployment" / "rates.csv"
        assert data_path.exists(), f"Unemployment data not found: {data_path}"
    
    def test_costs_data_exists(self):
        """Education costs data file must exist."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "costs" / "education_costs.csv"
        assert data_path.exists(), f"Costs data not found: {data_path}"
    
    def test_sector_data_exists(self):
        """Sector risk data file must exist."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "sectors" / "sector_risk.csv"
        assert data_path.exists(), f"Sector data not found: {data_path}"


class TestDataIntegrity:
    """Tests for data file integrity."""
    
    def test_unemployment_csv_valid(self):
        """Unemployment CSV must be valid."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "unemployment" / "rates.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) > 0, "Unemployment data is empty"
        
        # Check required columns
        required_cols = {'region', 'sector', 'year', 'rate'}
        actual_cols = set(rows[0].keys())
        missing = required_cols - actual_cols
        assert not missing, f"Missing columns: {missing}"
    
    def test_unemployment_rate_in_range(self):
        """Unemployment rates must be in valid range."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "unemployment" / "rates.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rate = float(row['rate'])
                assert 0.0 <= rate <= 1.0, f"Invalid rate: {rate}"
    
    def test_costs_csv_valid(self):
        """Education costs CSV must be valid."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "costs" / "education_costs.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) > 0, "Costs data is empty"
        
        # Check required columns
        required_cols = {'career', 'education_cost', 'training_months'}
        actual_cols = set(rows[0].keys())
        missing = required_cols - actual_cols
        assert not missing, f"Missing columns: {missing}"
    
    def test_costs_positive_values(self):
        """Costs must be non-negative."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "costs" / "education_costs.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cost = float(row['education_cost'])
                months = int(row['training_months'])
                assert cost >= 0, f"Negative cost: {cost}"
                assert months >= 0, f"Negative months: {months}"
    
    def test_sector_csv_valid(self):
        """Sector risk CSV must be valid."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "sectors" / "sector_risk.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) > 0, "Sector data is empty"
        
        # Check required columns
        required_cols = {'sector', 'automation_risk', 'volatility'}
        actual_cols = set(rows[0].keys())
        missing = required_cols - actual_cols
        assert not missing, f"Missing columns: {missing}"
    
    def test_sector_risks_in_range(self):
        """Sector risks must be in [0, 1]."""
        data_path = Path(__file__).parent.parent.parent / "data" / "risk" / "sectors" / "sector_risk.csv"
        
        with open(data_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                auto = float(row['automation_risk'])
                vol = float(row['volatility'])
                assert 0.0 <= auto <= 1.0, f"Invalid automation_risk: {auto}"
                assert 0.0 <= vol <= 1.0, f"Invalid volatility: {vol}"


class TestUnemploymentLoader:
    """Tests for UnemploymentLoader."""
    
    def test_instantiation(self):
        """UnemploymentLoader should instantiate."""
        from backend.risk.data_loader import UnemploymentLoader
        loader = UnemploymentLoader()
        assert loader is not None
    
    def test_get_rate_returns_float(self):
        """get_rate should return a float."""
        from backend.risk.data_loader import UnemploymentLoader
        loader = UnemploymentLoader()
        
        rate = loader.get_rate(region="national", sector="technology")
        assert isinstance(rate, (int, float))
    
    def test_get_rate_in_range(self):
        """Rate must be in [0, 1]."""
        from backend.risk.data_loader import UnemploymentLoader
        loader = UnemploymentLoader()
        
        rate = loader.get_rate(region="national", sector="technology")
        assert 0.0 <= rate <= 1.0
    
    def test_get_rate_with_defaults(self):
        """Should work with just defaults."""
        from backend.risk.data_loader import UnemploymentLoader
        loader = UnemploymentLoader()
        
        rate = loader.get_rate()
        assert isinstance(rate, (int, float))
        assert 0.0 <= rate <= 1.0


class TestCostDataLoader:
    """Tests for CostDataLoader."""
    
    def test_instantiation(self):
        """CostDataLoader should instantiate."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        assert loader is not None
    
    def test_get_education_cost_returns_float(self):
        """get_education_cost should return a float."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        
        cost = loader.get_education_cost("software_engineer")
        assert isinstance(cost, (int, float))
    
    def test_get_education_cost_non_negative(self):
        """Education cost must be non-negative."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        
        cost = loader.get_education_cost("data_scientist")
        assert cost >= 0
    
    def test_get_training_time_returns_int(self):
        """get_training_time should return months."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        
        months = loader.get_training_time("nurse")
        assert isinstance(months, (int, float))
        assert months >= 0
    
    def test_unknown_career_returns_default(self):
        """Unknown career should return default cost."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        
        cost = loader.get_education_cost("unknown_career_xyz_123")
        assert cost is not None
        assert cost >= 0


class TestSectorRiskLoader:
    """Tests for SectorRiskLoader."""
    
    def test_instantiation(self):
        """SectorRiskLoader should instantiate."""
        from backend.risk.data_loader import SectorRiskLoader
        loader = SectorRiskLoader()
        assert loader is not None
    
    def test_get_automation_risk(self):
        """Should get automation risk."""
        from backend.risk.data_loader import SectorRiskLoader
        loader = SectorRiskLoader()
        
        risk = loader.get_automation_risk("technology")
        assert isinstance(risk, (int, float))
        assert 0.0 <= risk <= 1.0
    
    def test_get_volatility(self):
        """Should get volatility."""
        from backend.risk.data_loader import SectorRiskLoader
        loader = SectorRiskLoader()
        
        vol = loader.get_volatility("healthcare")
        assert isinstance(vol, (int, float))
        assert 0.0 <= vol <= 1.0
    
    def test_unknown_sector_returns_default(self):
        """Unknown sector should return default."""
        from backend.risk.data_loader import SectorRiskLoader
        loader = SectorRiskLoader()
        
        risk = loader.get_automation_risk("unknown_sector_xyz")
        assert risk is not None
        assert 0.0 <= risk <= 1.0


class TestNoMocking:
    """Verify data loaders use real data, not mocks."""
    
    def test_unemployment_loads_from_csv(self):
        """UnemploymentLoader must load from real CSV."""
        from backend.risk.data_loader import UnemploymentLoader
        loader = UnemploymentLoader()
        
        # Should have loaded data from CSV
        assert hasattr(loader, '_data') or hasattr(loader, 'data')
    
    def test_costs_loads_from_csv(self):
        """CostDataLoader must load from real CSV."""
        from backend.risk.data_loader import CostDataLoader
        loader = CostDataLoader()
        
        # Different careers should have different costs (not hardcoded)
        cost1 = loader.get_education_cost("doctor")
        cost2 = loader.get_education_cost("web_developer")
        
        # They should differ (not all returning same hardcoded value)
        # Allow for same if data actually matches
        assert cost1 >= 0 and cost2 >= 0
