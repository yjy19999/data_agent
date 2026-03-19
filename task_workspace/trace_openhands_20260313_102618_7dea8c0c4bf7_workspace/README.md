# Simple Queue Implementation

This project provides a simple implementation of a queue data structure in Python.

## Features

- `enqueue(item)`: Add an item to the rear of the queue
- `dequeue()`: Remove and return the item from the front of the queue
- `peek()`: Return the item at the front of the queue without removing it
- `is_empty()`: Check if the queue is empty
- `size()`: Get the number of items in the queue

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

## Running Tests

To run the unit tests:

```bash
python -m unittest test_queue.py
```

For verbose output:

```bash
python -m unittest test_queue.py -v
```

## Implementation Details

The queue is implemented using Python's built-in list. While this implementation is simple and functional, note that using `pop(0)` for dequeue operations has O(n) time complexity because it requires shifting all remaining elements. For a more efficient implementation with O(1) operations, consider using `collections.deque`.