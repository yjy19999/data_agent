"""Tests for the greeting module."""

import pytest
from greeting import greet, greet_formal


class TestGreet:
    """Tests for the greet function."""

    def test_greet_simple_name(self):
        """Test greeting with a simple name."""
        result = greet("Alice")
        assert result == "Hello, Alice!"

    def test_greet_another_name(self):
        """Test greeting with a different name."""
        result = greet("Bob")
        assert result == "Hello, Bob!"

    def test_greet_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        result = greet("  Charlie  ")
        assert result == "Hello, Charlie!"

    def test_greet_single_character_name(self):
        """Test greeting with a single character name."""
        result = greet("X")
        assert result == "Hello, X!"

    def test_greet_multi_word_name(self):
        """Test greeting with a multi-word name."""
        result = greet("Mary Jane")
        assert result == "Hello, Mary Jane!"

    def test_greet_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet("")

    def test_greet_whitespace_only_raises_error(self):
        """Test that whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet("   ")

    def test_greet_none_raises_error(self):
        """Test that None raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet(None)


class TestGreetFormal:
    """Tests for the greet_formal function."""

    def test_greet_formal_with_title(self):
        """Test formal greeting with a custom title."""
        result = greet_formal("Smith", "Dr.")
        assert result == "Good day, Dr. Smith!"

    def test_greet_formal_default_title(self):
        """Test formal greeting with default title."""
        result = greet_formal("Johnson")
        assert result == "Good day, Mr./Ms. Johnson!"

    def test_greet_formal_professor_title(self):
        """Test formal greeting with Professor title."""
        result = greet_formal("Brown", "Professor")
        assert result == "Good day, Professor Brown!"

    def test_greet_formal_strips_whitespace(self):
        """Test that name whitespace is stripped."""
        result = greet_formal("  Davis  ", "Dr.")
        assert result == "Good day, Dr. Davis!"

    def test_greet_formal_empty_name_raises_error(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet_formal("", "Dr.")

    def test_greet_formal_whitespace_name_raises_error(self):
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet_formal("   ", "Dr.")

    def test_greet_formal_none_name_raises_error(self):
        """Test that None name raises ValueError."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            greet_formal(None, "Dr.")

    def test_greet_formal_empty_title(self):
        """Test formal greeting with empty title."""
        result = greet_formal("Test", "")
        assert result == "Good day,  Test!"


class TestGreetReturnTypes:
    """Tests to verify return types."""

    def test_greet_returns_string(self):
        """Test that greet returns a string."""
        result = greet("Test")
        assert isinstance(result, str)

    def test_greet_formal_returns_string(self):
        """Test that greet_formal returns a string."""
        result = greet_formal("Test", "Dr.")
        assert isinstance(result, str)
