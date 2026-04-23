# tests/interface/test_dto_contract.py
"""
GĐ7 Interface Contract Test Suite

Tests for ScoreResultDTO contract enforcement.
ALL tests must pass for merge gate.

Test Categories:
1. Type check - isinstance validation
2. Field presence - required attributes
3. Immutability - frozen dataclass
4. Legacy rejection - no legacy field access
5. Boundary - invalid DTO rejection
"""

import pytest
from dataclasses import FrozenInstanceError

from backend.scoring.dto import ScoreResultDTO, _validate_dto, dto_from_scored_career


# =====================================================
# Test Data Fixtures
# =====================================================

@pytest.fixture
def valid_components():
    """Valid SIMGR component scores."""
    return {
        "study": 0.8,
        "interest": 0.7,
        "market": 0.75,
        "growth": 0.6,
        "risk": 0.3,
    }


@pytest.fixture
def valid_meta():
    """Valid metadata dict."""
    return {
        "source": "test",
        "timestamp": "2026-02-17T12:00:00",
    }


@pytest.fixture
def valid_dto(valid_components, valid_meta):
    """Valid ScoreResultDTO instance."""
    return ScoreResultDTO(
        career_id="test_career",
        total_score=0.75,
        components=valid_components,
        rank=1,
        meta=valid_meta,
    )


# =====================================================
# Test 1: Type Check
# =====================================================

class TestTypeCheck:
    """Test DTO type validation."""
    
    def test_dto_is_score_result_dto(self, valid_dto):
        """Verify result is ScoreResultDTO instance."""
        assert isinstance(valid_dto, ScoreResultDTO)
    
    def test_validate_dto_accepts_valid(self, valid_dto):
        """Verify _validate_dto accepts valid DTO."""
        # Should not raise
        _validate_dto(valid_dto)
    
    def test_validate_dto_rejects_dict(self, valid_components, valid_meta):
        """Verify _validate_dto rejects dict."""
        invalid = {
            "career_id": "test",
            "total_score": 0.75,
            "components": valid_components,
            "rank": 1,
            "meta": valid_meta,
        }
        with pytest.raises(TypeError, match="Invalid scoring DTO"):
            _validate_dto(invalid)
    
    def test_validate_dto_rejects_none(self):
        """Verify _validate_dto rejects None."""
        with pytest.raises(TypeError, match="Invalid scoring DTO"):
            _validate_dto(None)
    
    def test_validate_dto_rejects_namedtuple(self, valid_components, valid_meta):
        """Verify _validate_dto rejects namedtuple."""
        from collections import namedtuple
        FakeDTO = namedtuple("ScoreResultDTO", ["career_id", "total_score", "components", "rank", "meta"])
        invalid = FakeDTO("test", 0.75, valid_components, 1, valid_meta)
        with pytest.raises(TypeError, match="Invalid scoring DTO"):
            _validate_dto(invalid)


# =====================================================
# Test 2: Field Presence
# =====================================================

class TestFieldPresence:
    """Test required field presence."""
    
    def test_has_career_id(self, valid_dto):
        """Verify DTO has career_id attribute."""
        assert hasattr(valid_dto, "career_id")
        assert valid_dto.career_id == "test_career"
    
    def test_has_total_score(self, valid_dto):
        """Verify DTO has total_score attribute."""
        assert hasattr(valid_dto, "total_score")
        assert 0.0 <= valid_dto.total_score <= 1.0
    
    def test_has_components(self, valid_dto):
        """Verify DTO has components attribute."""
        assert hasattr(valid_dto, "components")
        assert isinstance(valid_dto.components, dict)
    
    def test_has_rank(self, valid_dto):
        """Verify DTO has rank attribute."""
        assert hasattr(valid_dto, "rank")
        assert valid_dto.rank >= 1
    
    def test_has_meta(self, valid_dto):
        """Verify DTO has meta attribute."""
        assert hasattr(valid_dto, "meta")
        assert isinstance(valid_dto.meta, dict)
    
    def test_components_has_simgr_keys(self, valid_dto):
        """Verify components has all SIMGR keys."""
        required = {"study", "interest", "market", "growth", "risk"}
        assert required == set(valid_dto.components.keys())


# =====================================================
# Test 3: Immutability
# =====================================================

class TestImmutability:
    """Test DTO immutability (frozen dataclass)."""
    
    def test_cannot_modify_total_score(self, valid_dto):
        """Verify total_score cannot be modified."""
        with pytest.raises(FrozenInstanceError):
            valid_dto.total_score = 0.5
    
    def test_cannot_modify_career_id(self, valid_dto):
        """Verify career_id cannot be modified."""
        with pytest.raises(FrozenInstanceError):
            valid_dto.career_id = "new_id"
    
    def test_cannot_modify_rank(self, valid_dto):
        """Verify rank cannot be modified."""
        with pytest.raises(FrozenInstanceError):
            valid_dto.rank = 999
    
    def test_cannot_add_new_attribute(self, valid_dto):
        """Verify new attributes cannot be added."""
        with pytest.raises(FrozenInstanceError):
            valid_dto.new_field = "value"


# =====================================================
# Test 4: Legacy Rejection
# =====================================================

class TestLegacyRejection:
    """Test rejection of legacy field access."""
    
    def test_no_final_score_attribute(self, valid_dto):
        """Verify DTO has no final_score attribute."""
        with pytest.raises(AttributeError):
            _ = valid_dto.final_score
    
    def test_no_skill_score_attribute(self, valid_dto):
        """Verify DTO has no skill_score attribute."""
        with pytest.raises(AttributeError):
            _ = valid_dto.skill_score
    
    def test_no_confidence_score_attribute(self, valid_dto):
        """Verify DTO has no confidence_score attribute."""
        with pytest.raises(AttributeError):
            _ = valid_dto.confidence_score
    
    def test_no_legacy_score_attribute(self, valid_dto):
        """Verify DTO has no legacy_score attribute."""
        with pytest.raises(AttributeError):
            _ = valid_dto.legacy_score
    
    def test_no_normalized_score_attribute(self, valid_dto):
        """Verify DTO has no normalized_score attribute."""
        with pytest.raises(AttributeError):
            _ = valid_dto.normalized_score


# =====================================================
# Test 5: Boundary Validation
# =====================================================

class TestBoundaryValidation:
    """Test boundary validation (invalid DTO rejection)."""
    
    def test_reject_total_score_above_1(self, valid_components, valid_meta):
        """Reject total_score > 1.0."""
        with pytest.raises(ValueError, match="total_score must be in"):
            ScoreResultDTO(
                career_id="test",
                total_score=1.5,
                components=valid_components,
                rank=1,
                meta=valid_meta,
            )
    
    def test_reject_total_score_below_0(self, valid_components, valid_meta):
        """Reject total_score < 0.0."""
        with pytest.raises(ValueError, match="total_score must be in"):
            ScoreResultDTO(
                career_id="test",
                total_score=-0.1,
                components=valid_components,
                rank=1,
                meta=valid_meta,
            )
    
    def test_reject_rank_zero(self, valid_components, valid_meta):
        """Reject rank = 0."""
        with pytest.raises(ValueError, match="rank must be >= 1"):
            ScoreResultDTO(
                career_id="test",
                total_score=0.5,
                components=valid_components,
                rank=0,
                meta=valid_meta,
            )
    
    def test_reject_rank_negative(self, valid_components, valid_meta):
        """Reject negative rank."""
        with pytest.raises(ValueError, match="rank must be >= 1"):
            ScoreResultDTO(
                career_id="test",
                total_score=0.5,
                components=valid_components,
                rank=-1,
                meta=valid_meta,
            )
    
    def test_reject_missing_component(self, valid_meta):
        """Reject missing SIMGR component."""
        incomplete = {
            "study": 0.8,
            "interest": 0.7,
            # missing market, growth, risk
        }
        with pytest.raises(ValueError, match="Missing required components"):
            ScoreResultDTO(
                career_id="test",
                total_score=0.5,
                components=incomplete,
                rank=1,
                meta=valid_meta,
            )
    
    def test_reject_component_above_1(self, valid_meta):
        """Reject component score > 1.0."""
        invalid_components = {
            "study": 1.5,  # Invalid
            "interest": 0.7,
            "market": 0.75,
            "growth": 0.6,
            "risk": 0.3,
        }
        with pytest.raises(ValueError, match="must be in"):
            ScoreResultDTO(
                career_id="test",
                total_score=0.5,
                components=invalid_components,
                rank=1,
                meta=valid_meta,
            )
    
    def test_reject_component_below_0(self, valid_meta):
        """Reject component score < 0.0."""
        invalid_components = {
            "study": 0.8,
            "interest": -0.2,  # Invalid
            "market": 0.75,
            "growth": 0.6,
            "risk": 0.3,
        }
        with pytest.raises(ValueError, match="must be in"):
            ScoreResultDTO(
                career_id="test",
                total_score=0.5,
                components=invalid_components,
                rank=1,
                meta=valid_meta,
            )


# =====================================================
# Test 6: Conversion Function
# =====================================================

class TestDtoConversion:
    """Test dto_from_scored_career conversion."""
    
    def test_conversion_produces_dto(self):
        """Verify conversion produces valid DTO."""
        from unittest.mock import MagicMock
        
        # Create mock ScoredCareer
        mock_breakdown = MagicMock()
        mock_breakdown.study_score = 0.8
        mock_breakdown.interest_score = 0.7
        mock_breakdown.market_score = 0.75
        mock_breakdown.growth_score = 0.6
        mock_breakdown.risk_score = 0.3
        mock_breakdown.study_details = None
        mock_breakdown.interest_details = None
        mock_breakdown.market_details = None
        mock_breakdown.growth_details = None
        mock_breakdown.risk_details = None
        
        mock_scored = MagicMock()
        mock_scored.career_name = "Test Career"
        mock_scored.total_score = 0.75
        mock_scored.breakdown = mock_breakdown
        
        result = dto_from_scored_career(mock_scored, rank=1)
        
        assert isinstance(result, ScoreResultDTO)
        assert result.career_id == "Test Career"
        assert result.total_score == 0.75
        assert result.rank == 1
    
    def test_conversion_validates_dto(self):
        """Verify conversion result passes validation."""
        from unittest.mock import MagicMock
        
        mock_breakdown = MagicMock()
        mock_breakdown.study_score = 0.8
        mock_breakdown.interest_score = 0.7
        mock_breakdown.market_score = 0.75
        mock_breakdown.growth_score = 0.6
        mock_breakdown.risk_score = 0.3
        mock_breakdown.study_details = None
        mock_breakdown.interest_details = None
        mock_breakdown.market_details = None
        mock_breakdown.growth_details = None
        mock_breakdown.risk_details = None
        
        mock_scored = MagicMock()
        mock_scored.career_name = "Test"
        mock_scored.total_score = 0.5
        mock_scored.breakdown = mock_breakdown
        
        result = dto_from_scored_career(mock_scored, rank=1)
        
        # Should not raise
        _validate_dto(result)


# =====================================================
# Test 7: Integration with Engine
# =====================================================

class TestEngineIntegration:
    """Test DTO integration with scoring engine."""
    
    def test_engine_rank_dto_returns_list(self):
        """Verify rank_dto returns list of DTOs."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import UserProfile, CareerData
        from backend.scoring.config import ScoringConfig, SIMGRWeights
        
        # Create explicit config to avoid environment issues
        config = ScoringConfig(
            simgr_weights=SIMGRWeights(),
        )
        engine = RankingEngine(default_config=config)
        user = UserProfile(
            skills=["python", "data analysis"],
            interests=["AI", "machine learning"],
        )
        careers = [
            CareerData(
                name="Data Scientist",
                required_skills=["python"],
                ai_relevance=0.9,
            ),
        ]
        
        results = engine.rank_dto(user=user, careers=careers)
        
        assert isinstance(results, list)
        if results:  # May be empty if score below threshold
            for dto in results:
                assert isinstance(dto, ScoreResultDTO)
                _validate_dto(dto)
    
    def test_engine_facade_returns_dtos(self):
        """Verify rank_careers_dto facade returns DTOs."""
        from backend.scoring.engine import rank_careers_dto, RankingEngine
        from backend.scoring.models import UserProfile, CareerData
        from backend.scoring.config import ScoringConfig, SIMGRWeights
        
        # Set up global engine with valid config
        import backend.scoring.engine as engine_module
        config = ScoringConfig(simgr_weights=SIMGRWeights())
        engine_module._engine = RankingEngine(default_config=config)
        
        user = UserProfile(
            skills=["python"],
            interests=["software"],
        )
        careers = [
            CareerData(
                name="Software Engineer",
                required_skills=["python"],
            ),
        ]
        
        results = rank_careers_dto(user=user, careers=careers)
        
        assert isinstance(results, list)
        for dto in results:
            assert isinstance(dto, ScoreResultDTO)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
