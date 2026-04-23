# backend/tests/test_pdf_generator.py
"""
Comprehensive tests for PDF Export functionality.

Tests:
    - PDF generation from explanation data
    - PDF content sections
    - Deterministic document hash
    - Edge cases and error handling
"""

import hashlib
import json
import pytest
from pathlib import Path

try:
    from backend.explain.export.pdf_generator import (
        ExplainPdfGenerator,
        generate_explanation_pdf,
        REPORTLAB_AVAILABLE,
    )
except ImportError:
    REPORTLAB_AVAILABLE = False


# Skip all tests if reportlab not available
pytestmark = pytest.mark.skipif(
    not REPORTLAB_AVAILABLE,
    reason="reportlab not installed"
)


def make_explanation_data(trace_id: str = "trace_pdf_001") -> dict:
    """Create sample explanation data for PDF generation."""
    return {
        "explanation_id": f"exp-{trace_id}",
        "trace_id": trace_id,
        "model_id": "model-v1.2.3",
        "kb_version": "kb-2026.02.14",
        "confidence": 0.87,
        "created_at": "2026-02-14T10:30:00Z",
        "prediction": {
            "career": "Data Scientist",
            "confidence": 0.87,
        },
        "rule_path": [
            {
                "rule_id": "rule_logic_math_strength",
                "condition": "logic_score >= 70 AND math_score >= 70",
                "matched_features": {"logic_score": 85, "math_score": 90},
                "weight": 0.34,
            },
            {
                "rule_id": "rule_it_interest_alignment",
                "condition": "interest_it >= 65",
                "matched_features": {"interest_it": 88},
                "weight": 0.27,
            },
        ],
        "evidence": [
            {
                "source": "feature_snapshot",
                "key": "math_score",
                "value": 90,
                "weight": 0.9,
            },
            {
                "source": "feature_snapshot",
                "key": "logic_score",
                "value": 85,
                "weight": 0.85,
            },
            {
                "source": "model_distribution",
                "key": "rank_1",
                "value": {"career": "Data Scientist", "probability": 0.87},
                "weight": 0.87,
            },
        ],
        "feature_snapshot": {
            "math_score": 90,
            "physics_score": 78,
            "logic_score": 85,
            "interest_it": 88,
            "creativity_score": 72,
        },
        "integrity": {
            "record_hash": "a1b2c3d4e5f6789012345678901234567890abcd",
            "prev_hash": "0987654321fedcba0987654321fedcba09876543",
        },
    }


class TestPdfGeneratorInit:
    """Tests for PDF generator initialization."""

    def test_init_default_settings(self):
        generator = ExplainPdfGenerator()
        assert generator is not None

    def test_init_custom_margins(self):
        generator = ExplainPdfGenerator(margin=1.0)
        assert generator is not None


class TestPdfGeneration:
    """Tests for PDF generation."""

    def test_generate_pdf_returns_bytes(self):
        """PDF generation should return bytes."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_pdf_starts_with_header(self):
        """PDF should start with %PDF header."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        pdf_bytes = generator.generate(data)
        
        assert pdf_bytes.startswith(b'%PDF')

    def test_generate_with_graph(self):
        """PDF should include graph section when provided."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["graph"] = {
            "nodes": [{"id": "node1"}, {"id": "node2"}],
            "edges": [
                {"source": "node1", "target": "node2", "edge_type": "dependency"}
            ],
            "adjacency": {"node1": ["node2"]},
        }
        
        pdf_bytes = generator.generate(data, include_graph=True)
        
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_generate_without_graph(self):
        """PDF should work without graph section."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        pdf_bytes = generator.generate(data, include_graph=False)
        
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_generate_without_integrity(self):
        """PDF should work without integrity section."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        del data["integrity"]
        
        pdf_bytes = generator.generate(data, include_integrity=False)
        
        assert isinstance(pdf_bytes, bytes)


class TestPdfContentSections:
    """Tests for PDF content sections."""

    def test_minimal_data(self):
        """PDF should handle minimal data gracefully."""
        generator = ExplainPdfGenerator()
        data = {
            "trace_id": "minimal_trace",
            "confidence": 0.5,
        }
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_empty_rule_path(self):
        """PDF should handle empty rule path."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["rule_path"] = []
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)

    def test_empty_evidence(self):
        """PDF should handle empty evidence."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["evidence"] = []
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)

    def test_empty_features(self):
        """PDF should handle empty feature snapshot."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["feature_snapshot"] = {}
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)


class TestDeterministicHash:
    """Tests for deterministic document hashing."""

    def test_same_data_same_hash(self):
        """Same input data should produce same document hash."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data("trace_hash_001")
        
        hash1 = generator._compute_document_hash(data)
        hash2 = generator._compute_document_hash(data)
        
        assert hash1 == hash2

    def test_different_data_different_hash(self):
        """Different input data should produce different hash."""
        generator = ExplainPdfGenerator()
        data1 = make_explanation_data("trace_hash_001")
        data2 = make_explanation_data("trace_hash_002")
        
        hash1 = generator._compute_document_hash(data1)
        hash2 = generator._compute_document_hash(data2)
        
        assert hash1 != hash2


class TestConvenienceFunction:
    """Tests for generate_explanation_pdf convenience function."""

    def test_generate_returns_bytes(self):
        data = make_explanation_data()
        
        pdf_bytes = generate_explanation_pdf(data)
        
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b'%PDF')

    def test_generate_saves_to_file(self, tmp_path):
        data = make_explanation_data()
        output_file = tmp_path / "test_output.pdf"
        
        pdf_bytes = generate_explanation_pdf(data, output_path=output_file)
        
        assert output_file.exists()
        assert output_file.read_bytes() == pdf_bytes

    def test_generate_creates_parent_dirs(self, tmp_path):
        data = make_explanation_data()
        output_file = tmp_path / "nested" / "dirs" / "output.pdf"
        
        generate_explanation_pdf(data, output_path=output_file)
        
        assert output_file.exists()


class TestPdfEdgeCases:
    """Tests for edge cases and error handling."""

    def test_long_values_truncated(self):
        """Long values should be truncated to fit."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["evidence"].append({
            "source": "test_source",
            "key": "very_long_key",
            "value": "x" * 1000,  # Very long value
            "weight": 0.5,
        })
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)

    def test_many_rules(self):
        """PDF should handle many rules."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        # Add 50 rules
        data["rule_path"] = [
            {
                "rule_id": f"rule_{i}",
                "condition": f"feature_{i} >= {i * 10}",
                "matched_features": {f"feature_{i}": i * 10 + 5},
                "weight": i / 100,
            }
            for i in range(50)
        ]
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_unicode_content(self):
        """PDF should handle Unicode characters."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["prediction"]["career"] = "Kỹ sư AI"  # Vietnamese
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)

    def test_nested_evidence_values(self):
        """PDF should handle nested evidence values."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        data["evidence"].append({
            "source": "complex",
            "key": "nested_data",
            "value": {
                "level1": {
                    "level2": {
                        "level3": [1, 2, 3]
                    }
                }
            },
            "weight": 0.5,
        })
        
        pdf_bytes = generator.generate(data)
        
        assert isinstance(pdf_bytes, bytes)


class TestPdfConsistency:
    """Tests for PDF generation consistency."""

    def test_multiple_generations_consistent_size(self):
        """Multiple generations should produce similar sized PDFs."""
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        pdf1 = generator.generate(data)
        pdf2 = generator.generate(data)
        pdf3 = generator.generate(data)
        
        # Sizes should be within 5% of each other
        sizes = [len(pdf1), len(pdf2), len(pdf3)]
        avg_size = sum(sizes) / len(sizes)
        
        for size in sizes:
            assert abs(size - avg_size) / avg_size < 0.05

    def test_generation_is_reasonably_fast(self):
        """PDF generation should complete in reasonable time."""
        import time
        
        generator = ExplainPdfGenerator()
        data = make_explanation_data()
        
        start = time.time()
        for _ in range(10):
            generator.generate(data)
        elapsed = time.time() - start
        
        # Should generate 10 PDFs in under 5 seconds
        assert elapsed < 5.0
