# Stack

A simple stack data structure implementation in Python using a list.

## Installation

No external dependencies required. The module uses only Python's built-in types.

To use, simply copy `stack.py` to your project and import it:

```python
from stack import Stack
```

## Usage Examples

### Basic Operations

```python
from stack import Stack

# Create a new stack
stack = Stack()

# Push items onto the stack
stack.push(10)
stack.push(20)
stack.push(30)

# Peek at the top item
print(stack.peek())  # Output: 30

# Pop items off the stack
print(stack.pop())   # Output: 30
print(stack.pop())   # Output: 20

# Check if empty
print(stack.is_empty())  # Output: False

# Get the size
print(stack.size())      # Output: 1
print(len(stack))        # Output: 1
```

### Working with Different Types

```python
from stack import Stack

# Stack can hold any Python object
stack = Stack()
stack.push("hello")
stack.push([1, 2, 3])
stack.push({"key": "value"})

print(stack.pop())  # Output: {'key': 'value'}
print(stack.pop())  # Output: [1, 2, 3]
```

### Error Handling

```python
from stack import Stack

stack = Stack()

# Popping from an empty stack raises IndexError
try:
    stack.pop()
except IndexError as e:
    print(f"Error: {e}")  # Output: Error: pop from empty stack

# Peeking at an empty stack raises IndexError
try:
    stack.peek()
except IndexError as e:
    print(f"Error: {e}")  # Output: Error: peek from empty stack
```

## API Reference

### `Stack` Class

A last-in, first-out (LIFO) data structure.

#### Constructor

```python
Stack()
```

Creates an empty stack.

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `push(item)` | `item`: Any - The item to add | `None` | Add an item to the top of the stack |
| `pop()` | None | `Any` | Remove and return the item from the top of the stack. Raises `IndexError` if the stack is empty |
| `peek()` | None | `Any` | Return the item at the top of the stack without removing it. Raises `IndexError` if the stack is empty |
| `is_empty()` | None | `bool` | Return `True` if the stack is empty, `False` otherwise |
| `size()` | None | `int` | Return the number of items in the stack |

#### Special Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `len(stack)` | `int` | Return the number of items in the stack |
| `repr(stack)` | `str` | Return a string representation of the stack (e.g., `Stack([1, 2, 3])`) |

## Running Tests

To run the test suite using pytest:

```bash
pytest test_stack.py -v
```
