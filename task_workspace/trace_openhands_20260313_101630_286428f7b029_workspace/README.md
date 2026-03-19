# Calculator Module

A simple Python calculator module that provides basic arithmetic operations through a Calculator class.

## Description

This module implements a Calculator class with methods for performing basic arithmetic operations: addition, subtraction, multiplication, and division. The division method includes error handling for division by zero.

## Installation

No external dependencies are required. This module works with Python's standard library only.

To use this module, simply copy `calculator.py` to your project directory or install it as a package.

## Usage

```python
from calculator import Calculator

# Create an instance of the Calculator
calc = Calculator()

# Perform basic arithmetic operations
result = calc.add(5, 3)        # Returns 8
result = calc.subtract(10, 4)  # Returns 6
result = calc.multiply(3, 7)   # Returns 21
result = calc.divide(15, 3)    # Returns 5.0

# Division by zero raises a ValueError
try:
    result = calc.divide(10, 0)
except ValueError as e:
    print(e)  # Prints "Cannot divide by zero"
```

## API Reference

### Calculator Class

#### `add(a, b)`
Performs addition of two numbers.
- **Parameters:**
  - `a` (int/float): First operand
  - `b` (int/float): Second operand
- **Returns:** Sum of `a` and `b`

#### `subtract(a, b)`
Performs subtraction of two numbers.
- **Parameters:**
  - `a` (int/float): Minuend
  - `b` (int/float): Subtrahend
- **Returns:** Difference of `a` and `b`

#### `multiply(a, b)`
Performs multiplication of two numbers.
- **Parameters:**
  - `a` (int/float): First operand
  - `b` (int/float): Second operand
- **Returns:** Product of `a` and `b`

#### `divide(a, b)`
Performs division of two numbers.
- **Parameters:**
  - `a` (int/float): Dividend
  - `b` (int/float): Divisor
- **Returns:** Quotient of `a` and `b`
- **Raises:** 
  - `ValueError`: If `b` is zero