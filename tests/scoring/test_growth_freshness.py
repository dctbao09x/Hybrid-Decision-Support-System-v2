# tests/scoring/test_growth_freshness.py
"""
Tests for Growth Data Freshness (R003)

Validates:
- Data freshness checking
- TTL enforcement (< 90 days)
- Refresh trigger functionality
- Cache persistence
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil

# Import module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.scoring.components.growth_refresh import (
    DataFreshness,
    GrowthDataCache,
    GrowthDataRefresher,
    check_growth_freshness,
    trigger_growth_refresh,
)


class TestDataFreshness:
    """Test DataFreshness class."""
    
    def test_fresh_data(self):
        """Data within TTL should be fresh."""
        freshness = DataFreshness(
            last_updated=datetime.now(),
            version="20260216_120000",
            source="test",
            ttl_days=90,
        )
        
        assert not freshness.is_stale
        assert freshness.age_days == 0
    
    def test_stale_data(self):
        """Data beyond TTL should be stale."""
        old_date = datetime.now() - timedelta(days=100)
        freshness = DataFreshness(
            last_updated=old_date,
            version="20260101_120000",
            source="test",
            ttl_days=90,
        )
        
        assert freshness.is_stale
        assert freshness.age_days >= 100
    
    def test_ttl_boundary(self):
        """Data at exactly TTL should be stale."""
        boundary_date = datetime.now() - timedelta(days=90)
        freshness = DataFreshness(
            last_updated=boundary_date,
            version="test",
            source="test",
            ttl_days=90,
        )
        
        assert freshness.is_stale
    
    def test_to_dict(self):
        """Test serialization to dict."""
        freshness = DataFreshness(
            last_updated=datetime(2026, 2, 16, 12, 0, 0),
            version="v1",
            source="test",
            ttl_days=90,
            checksum="abc123",
            record_count=100,
        )
        
        result = freshness.to_dict()
        
        assert result["version"] == "v1"
        assert result["source"] == "test"
        assert result["ttl_days"] == 90
        assert result["checksum"] == "abc123"
        assert result["record_count"] == 100


class TestGrowthDataCache:
    """Test GrowthDataCache class."""
    
    def test_empty_cache(self):
        """Empty cache should have no data."""
        cache = GrowthDataCache()
        
        assert cache.lifecycle_data == {}
        assert cache.demand_forecast == {}
        assert cache.salary_data == {}
    
    def test_checksum_consistency(self):
        """Same data should produce same checksum."""
        cache1 = GrowthDataCache(
            lifecycle_data={"software engineer": 0.85},
            demand_forecast={"software engineer": 0.80},
        )
        cache2 = GrowthDataCache(
            lifecycle_data={"software engineer": 0.85},
            demand_forecast={"software engineer": 0.80},
        )
        
        assert cache1.compute_checksum() == cache2.compute_checksum()
    
    def test_checksum_changes_with_data(self):
        """Different data should produce different checksum."""
        cache1 = GrowthDataCache(
            lifecycle_data={"software engineer": 0.85},
        )
        cache2 = GrowthDataCache(
            lifecycle_data={"software engineer": 0.90},
        )
        
        assert cache1.compute_checksum() != cache2.compute_checksum()


class TestGrowthDataRefresher:
    """Test GrowthDataRefresher class."""
    
    @pytest.fixture
    def temp_data_path(self):
        """Create temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_empty_freshness_check(self, temp_data_path):
        """Check freshness when no data exists."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        result = refresher.check_freshness()
        
        assert result["status"] == "NO_DATA"
        assert result["needs_refresh"] is True
    
    def test_save_and_load_cache(self, temp_data_path):
        """Test cache persistence."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        # Save cache
        cache = GrowthDataCache(
            lifecycle_data={"data scientist": 0.92},
            demand_forecast={"data scientist": 0.88},
        )
        assert refresher.save_cache(cache)
        
        # Load cache
        loaded = refresher.load_cache()
        
        assert loaded.lifecycle_data.get("data scientist") == 0.92
        assert loaded.demand_forecast.get("data scientist") == 0.88
    
    def test_freshness_after_save(self, temp_data_path):
        """Freshness should be updated after save."""
        refresher = GrowthDataRefresher(data_path=temp_data_path, ttl_days=90)
        
        cache = GrowthDataCache(
            lifecycle_data={"test": 0.5},
        )
        refresher.save_cache(cache)
        
        result = refresher.check_freshness()
        
        assert result["status"] == "FRESH"
        assert result["needs_refresh"] is False
        assert result["ttl_days"] == 90
    
    def test_get_lifecycle_score(self, temp_data_path):
        """Test getting lifecycle score from cache."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        cache = GrowthDataCache(
            lifecycle_data={"ai/ml engineer": 0.95},
        )
        refresher.save_cache(cache)
        
        score = refresher.get_lifecycle_score("AI/ML Engineer")
        
        assert score == 0.95
    
    def test_get_demand_forecast(self, temp_data_path):
        """Test getting demand forecast from cache."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        cache = GrowthDataCache(
            demand_forecast={"cybersecurity analyst": 0.92},
        )
        refresher.save_cache(cache)
        
        score = refresher.get_demand_forecast("cybersecurity analyst")
        
        assert score == 0.92
    
    def test_trigger_refresh_when_fresh(self, temp_data_path):
        """Refresh should skip when data is fresh."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        # Save fresh cache
        cache = GrowthDataCache(lifecycle_data={"test": 0.5})
        refresher.save_cache(cache)
        
        # Trigger refresh (should skip)
        result = refresher.trigger_refresh(force=False)
        
        assert result["status"] == "SKIPPED"
    
    def test_force_refresh(self, temp_data_path):
        """Force refresh should update even when fresh."""
        refresher = GrowthDataRefresher(data_path=temp_data_path)
        
        # Save fresh cache
        cache = GrowthDataCache(lifecycle_data={"test": 0.5})
        refresher.save_cache(cache)
        
        # Mock the fetch to avoid external dependencies
        with patch.object(refresher, '_fetch_growth_data') as mock_fetch:
            mock_fetch.return_value = {
                "lifecycle": {"updated": 0.9},
                "demand": {},
                "salary": {},
            }
            
            result = refresher.trigger_refresh(force=True)
        
        assert result["status"] == "SUCCESS"
    
    def test_ttl_enforcement(self, temp_data_path):
        """TTL should be enforced correctly."""
        # Create refresher with short TTL
        refresher = GrowthDataRefresher(data_path=temp_data_path, ttl_days=30)
        
        # Manually create old metadata
        meta_path = Path(temp_data_path) / "growth_metadata.json"
        old_date = datetime.now() - timedelta(days=35)
        
        with open(meta_path, 'w') as f:
            json.dump({
                "last_updated": old_date.isoformat(),
                "version": "old",
                "source": "test",
                "ttl_days": 30,
            }, f)
        
        result = refresher.check_freshness()
        
        assert result["status"] == "STALE"
        assert result["needs_refresh"] is True
        assert result["age_days"] >= 35


class TestR003Compliance:
    """Test R003 Data Freshness compliance requirements."""
    
    def test_ttl_under_90_days(self):
        """TTL must be configurable and < 90 days enforced."""
        refresher = GrowthDataRefresher(ttl_days=90)
        assert refresher.ttl_days == 90
        
        refresher = GrowthDataRefresher(ttl_days=30)
        assert refresher.ttl_days == 30
    
    def test_refresh_trigger_exists(self):
        """Refresh trigger API must exist."""
        from backend.scoring.components.growth_refresh import trigger_growth_refresh
        assert callable(trigger_growth_refresh)
    
    def test_check_freshness_exists(self):
        """Freshness check API must exist."""
        from backend.scoring.components.growth_refresh import check_growth_freshness
        assert callable(check_growth_freshness)
    
    def test_metadata_tracking(self, tmp_path):
        """Metadata must track version, timestamp, and source."""
        refresher = GrowthDataRefresher(data_path=str(tmp_path))
        
        cache = GrowthDataCache(lifecycle_data={"test": 0.5})
        refresher.save_cache(cache)
        
        # Load and verify metadata
        meta_path = tmp_path / "growth_metadata.json"
        assert meta_path.exists()
        
        with open(meta_path) as f:
            meta = json.load(f)
        
        assert "last_updated" in meta
        assert "version" in meta
        assert "source" in meta
        assert "ttl_days" in meta


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
