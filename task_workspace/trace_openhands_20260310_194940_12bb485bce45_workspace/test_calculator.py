"""Tests for the Calculator class."""

import pytest
from calculator import Calculator


class TestCalculator:
    """Test suite for the Calculator class."""

    def setup_method(self):
        """Set up a Calculator instance for each test."""
        self.calc = Calculator()

    # Addition tests
    def test_add_positive_numbers(self):
        """Test adding two positive numbers."""
        assert self.calc.add(2, 3) == 5

    def test_add_negative_numbers(self):
        """Test adding two negative numbers."""
        assert self.calc.add(-2, -3) == -5

    def test_add_mixed_sign_numbers(self):
        """Test adding numbers with different signs."""
        assert self.calc.add(-2, 3) == 1
        assert self.calc.add(2, -3) == -1

    def test_add_zero(self):
        """Test adding with zero."""
        assert self.calc.add(0, 5) == 5
        assert self.calc.add(5, 0) == 5
        assert self.calc.add(0, 0) == 0

    def test_add_floats(self):
        """Test adding floating point numbers."""
        assert self.calc.add(2.5, 3.5) == 6.0
        assert self.calc.add(0.1, 0.2) == pytest.approx(0.3)

    # Subtraction tests
    def test_subtract_positive_numbers(self):
        """Test subtracting two positive numbers."""
        assert self.calc.subtract(5, 3) == 2

    def test_subtract_negative_numbers(self):
        """Test subtracting two negative numbers."""
        assert self.calc.subtract(-5, -3) == -2

    def test_subtract_mixed_sign_numbers(self):
        """Test subtracting numbers with different signs."""
        assert self.calc.subtract(-5, 3) == -8
        assert self.calc.subtract(5, -3) == 8

    def test_subtract_zero(self):
        """Test subtracting with zero."""
        assert self.calc.subtract(5, 0) == 5
        assert self.calc.subtract(0, 5) == -5
        assert self.calc.subtract(0, 0) == 0

    def test_subtract_floats(self):
        """Test subtracting floating point numbers."""
        assert self.calc.subtract(5.5, 2.5) == 3.0
        assert self.calc.subtract(0.3, 0.1) == pytest.approx(0.2)

    def test_subtract_larger_from_smaller(self):
        """Test subtracting a larger number from a smaller one."""
        assert self.calc.subtract(3, 5) == -2

    # Multiplication tests
    def test_multiply_positive_numbers(self):
        """Test multiplying two positive numbers."""
        assert self.calc.multiply(2, 3) == 6

    def test_multiply_negative_numbers(self):
        """Test multiplying two negative numbers."""
        assert self.calc.multiply(-2, -3) == 6

    def test_multiply_mixed_sign_numbers(self):
        """Test multiplying numbers with different signs."""
        assert self.calc.multiply(-2, 3) == -6
        assert self.calc.multiply(2, -3) == -6

    def test_multiply_by_zero(self):
        """Test multiplying by zero."""
        assert self.calc.multiply(5, 0) == 0
        assert self.calc.multiply(0, 5) == 0
        assert self.calc.multiply(0, 0) == 0

    def test_multiply_by_one(self):
        """Test multiplying by one."""
        assert self.calc.multiply(5, 1) == 5
        assert self.calc.multiply(1, 5) == 5

    def test_multiply_floats(self):
        """Test multiplying floating point numbers."""
        assert self.calc.multiply(2.5, 2) == 5.0
        assert self.calc.multiply(0.1, 0.2) == pytest.approx(0.02)

    def test_multiply_large_numbers(self):
        """Test multiplying large numbers."""
        assert self.calc.multiply(1000000, 1000000) == 1000000000000

    # Division tests
    def test_divide_positive_numbers(self):
        """Test dividing two positive numbers."""
        assert self.calc.divide(6, 2) == 3

    def test_divide_negative_numbers(self):
        """Test dividing two negative numbers."""
        assert self.calc.divide(-6, -2) == 3

    def test_divide_mixed_sign_numbers(self):
        """Test dividing numbers with different signs."""
        assert self.calc.divide(-6, 2) == -3
        assert self.calc.divide(6, -2) == -3

    def test_divide_zero_by_number(self):
        """Test dividing zero by a number."""
        assert self.calc.divide(0, 5) == 0

    def test_divide_by_one(self):
        """Test dividing by one."""
        assert self.calc.divide(5, 1) == 5

    def test_divide_floats(self):
        """Test dividing floating point numbers."""
        assert self.calc.divide(5.0, 2.0) == 2.5
        assert self.calc.divide(1, 3) == pytest.approx(0.333333, rel=1e-5)

    def test_divide_non_integer_result(self):
        """Test division that results in a non-integer."""
        assert self.calc.divide(7, 2) == 3.5

    def test_divide_by_zero_raises_value_error(self):
        """Test that dividing by zero raises ValueError."""
        with pytest.raises(ValueError, match="Division by zero is not allowed"):
            self.calc.divide(5, 0)

    def test_divide_zero_by_zero_raises_value_error(self):
        """Test that dividing zero by zero raises ValueError."""
        with pytest.raises(ValueError, match="Division by zero is not allowed"):
            self.calc.divide(0, 0)

    def test_divide_negative_by_zero_raises_value_error(self):
        """Test that dividing a negative by zero raises ValueError."""
        with pytest.raises(ValueError, match="Division by zero is not allowed"):
            self.calc.divide(-5, 0)
