"""A simple calculator module with basic arithmetic operations."""


class Calculator:
    """A calculator class that performs basic arithmetic operations."""

    def add(self, a: float, b: float) -> float:
        """Add two numbers.

        Args:
            a: First number.
            b: Second number.

        Returns:
            The sum of a and b.
        """
        return a + b

    def subtract(self, a: float, b: float) -> float:
        """Subtract the second number from the first.

        Args:
            a: First number.
            b: Second number.

        Returns:
            The difference of a and b.
        """
        return a - b

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers.

        Args:
            a: First number.
            b: Second number.

        Returns:
            The product of a and b.
        """
        return a * b

    def divide(self, a: float, b: float) -> float:
        """Divide the first number by the second.

        Args:
            a: Numerator.
            b: Denominator.

        Returns:
            The quotient of a divided by b.

        Raises:
            ValueError: If b is zero (division by zero).
        """
        if b == 0:
            raise ValueError("Division by zero is not allowed")
        return a / b
