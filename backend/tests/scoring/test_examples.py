"""
Tests for backend/scoring/examples.py

Ensures examples run without errors.
"""

import pytest
import sys
from io import StringIO
from unittest.mock import patch
from backend.scoring.examples import (
    example_1_basic_scoring,
    example_2_custom_strategy,
    example_3_custom_weights,
    example_4_error_handling,
    example_5_complete_profile
)


class TestExamples:
    """Test that examples execute without errors."""

    @patch('builtins.print')
    def test_example_1_basic_scoring(self, mock_print):
        """Test example 1 runs without error."""
        example_1_basic_scoring()
        # Verify print was called (indicating successful execution)
        assert mock_print.called

    @patch('builtins.print')
    def test_example_2_custom_strategy(self, mock_print):
        """Test example 2 runs without error."""
        example_2_custom_strategy()
        assert mock_print.called

    @patch('builtins.print')
    def test_example_3_custom_weights(self, mock_print):
        """Test example 3 runs without error."""
        example_3_custom_weights()
        assert mock_print.called

    @patch('builtins.print')
    def test_example_4_error_handling(self, mock_print):
        """Test example 4 runs without error."""
        example_4_error_handling()
        assert mock_print.called

    @patch('builtins.print')
    def test_example_5_complete_profile(self, mock_print):
        """Test example 5 runs without error."""
        example_5_complete_profile()
        assert mock_print.called

    def test_examples_import(self):
        """Test examples module imports correctly."""
        # This test ensures no import errors in examples.py
        from backend.scoring import examples
        assert hasattr(examples, 'example_1_basic_scoring')
        assert hasattr(examples, 'example_5_complete_profile')
