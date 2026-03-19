# Priority Queue

A simple priority queue implementation in Python that returns items based on their priority order.

## Description

This module provides a `PriorityQueue` class that allows you to add items with associated priority values and retrieve them in priority order (lowest priority values are retrieved first). The implementation uses Python's built-in `heapq` module for efficient operations.

## Installation

No installation required. The module only uses Python's standard library.

## Dependencies

- Python 3.x
- `heapq` (standard library)

## Usage

```python
from priority_queue import PriorityQueue

# Create a new priority queue
pq = PriorityQueue()

# Add items with priorities
pq.push("Low priority task", 3)
pq.push("High priority task", 1)
pq.push("Medium priority task", 2)

# Retrieve items in priority order
highest_priority_item = pq.pop()  # Returns "High priority task"
next_item = pq.pop()              # Returns "Medium priority task"
last_item = pq.pop()              # Returns "Low priority task"

# Peek at the highest priority item without removing it
pq.push("Urgent task", 0)
urgent_task = pq.peek()           # Returns "Urgent task" (without removing it)
```

## API Reference

### `PriorityQueue()`

Creates a new empty priority queue.

#### Methods

##### `push(item, priority)`
Add an item to the priority queue.

- **Parameters:**
  - `item`: The item to add to the queue
  - `priority`: The priority of the item (lower values have higher priority)
- **Returns:** None

##### `pop()`
Remove and return the highest priority item from the queue.

- **Parameters:** None
- **Returns:** The item with the highest priority (lowest priority value)
- **Raises:** `IndexError` if the queue is empty

##### `peek()`
Return the highest priority item without removing it from the queue.

- **Parameters:** None
- **Returns:** The item with the highest priority (lowest priority value)
- **Raises:** `IndexError` if the queue is empty

##### `is_empty()`
Check if the priority queue is empty.

- **Parameters:** None
- **Returns:** `bool` - True if the queue is empty, False otherwise

##### `size()`
Get the number of items in the priority queue.

- **Parameters:** None
- **Returns:** `int` - The number of items in the queue