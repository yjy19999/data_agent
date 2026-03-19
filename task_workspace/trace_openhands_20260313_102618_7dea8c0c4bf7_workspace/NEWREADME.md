# Simple Queue Implementation

A simple queue data structure implementation in Python following FIFO (First In, First Out) semantics.

## Description

This module provides a `Queue` class that implements a basic queue data structure with standard operations:
- `enqueue`: Add an item to the rear of the queue
- `dequeue`: Remove and return the item from the front of the queue
- `peek`: View the front item without removing it

## Installation

No external dependencies are required. The implementation uses only Python standard library features.

## Usage

```python
from queue import Queue

# Create a new queue
q = Queue()

# Add items to the queue
q.enqueue(1)
q.enqueue(2)
q.enqueue(3)

# Check queue size
print(q.size())  # Output: 3

# Peek at the front item
print(q.peek())  # Output: 1

# Remove items from the queue (FIFO order)
print(q.dequeue())  # Output: 1
print(q.dequeue())  # Output: 2
print(q.dequeue())  # Output: 3

# Check if queue is empty
print(q.is_empty())  # Output: True
```

## API Reference

### `Queue` Class

#### `Queue()`
Creates a new empty queue.

#### `enqueue(item)`
Add an item to the rear of the queue.

**Parameters:**
- `item`: The item to be added to the queue (any type)

**Returns:**
- `None`

#### `dequeue()`
Remove and return the item at the front of the queue.

**Parameters:**
- None

**Returns:**
- The item that was at the front of the queue

**Raises:**
- `IndexError`: If the queue is empty

#### `peek()`
Return the item at the front of the queue without removing it.

**Parameters:**
- None

**Returns:**
- The item at the front of the queue

**Raises:**
- `IndexError`: If the queue is empty

#### `is_empty()`
Check if the queue is empty.

**Parameters:**
- None

**Returns:**
- `bool`: True if the queue is empty, False otherwise

#### `size()`
Return the number of items in the queue.

**Parameters:**
- None

**Returns:**
- `int`: The number of items in the queue

## Implementation Notes

The queue is implemented using Python's built-in list. While this implementation is simple and functional, note that using `pop(0)` for dequeue operations has O(n) time complexity because it requires shifting all remaining elements. For a more efficient implementation with O(1) operations, consider using `collections.deque`.