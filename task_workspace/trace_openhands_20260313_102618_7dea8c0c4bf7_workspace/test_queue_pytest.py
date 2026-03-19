import pytest
from queue import Queue

def test_enqueue_increases_size():
    """Test that enqueue increases the queue size."""
    queue = Queue()
    assert queue.size() == 0
    queue.enqueue(1)
    assert queue.size() == 1
    queue.enqueue(2)
    assert queue.size() == 2

def test_dequeue_decreases_size():
    """Test that dequeue decreases the queue size."""
    queue = Queue()
    queue.enqueue(1)
    queue.enqueue(2)
    assert queue.size() == 2
    queue.dequeue()
    assert queue.size() == 1
    queue.dequeue()
    assert queue.size() == 0

def test_fifo_order():
    """Test that queue follows FIFO (First In, First Out) order."""
    queue = Queue()
    queue.enqueue(1)
    queue.enqueue(2)
    queue.enqueue(3)
    
    # First item dequeued should be the first one enqueued
    assert queue.dequeue() == 1
    assert queue.dequeue() == 2
    assert queue.dequeue() == 3

def test_peek_returns_front_item():
    """Test that peek returns the front item without removing it."""
    queue = Queue()
    queue.enqueue(1)
    queue.enqueue(2)
    
    # Peek should return first item
    assert queue.peek() == 1
    # Size should remain unchanged
    assert queue.size() == 2
    
    # After dequeue, peek should return the new front item
    queue.dequeue()
    assert queue.peek() == 2

def test_peek_on_empty_queue_raises_error():
    """Test that peek on an empty queue raises IndexError."""
    queue = Queue()
    with pytest.raises(IndexError, match="peek from an empty queue"):
        queue.peek()

def test_dequeue_on_empty_queue_raises_error():
    """Test that dequeue on an empty queue raises IndexError."""
    queue = Queue()
    with pytest.raises(IndexError, match="dequeue from an empty queue"):
        queue.dequeue()

def test_is_empty_on_new_queue():
    """Test that a new queue is empty."""
    queue = Queue()
    assert queue.is_empty() == True

def test_is_empty_on_non_empty_queue():
    """Test that a queue with items is not empty."""
    queue = Queue()
    queue.enqueue(1)
    assert queue.is_empty() == False

def test_is_empty_after_dequeueing_all_items():
    """Test that queue is empty after dequeueing all items."""
    queue = Queue()
    queue.enqueue(1)
    queue.enqueue(2)
    queue.dequeue()
    queue.dequeue()
    assert queue.is_empty() == True

def test_mixed_operations():
    """Test mixed queue operations to ensure correct behavior."""
    queue = Queue()
    
    # Start with some items
    queue.enqueue("first")
    queue.enqueue("second")
    queue.enqueue("third")
    
    # Peek at front item
    assert queue.peek() == "first"
    
    # Dequeue one item
    assert queue.dequeue() == "first"
    
    # Add another item
    queue.enqueue("fourth")
    
    # Dequeue remaining items in FIFO order
    assert queue.dequeue() == "second"
    assert queue.dequeue() == "third"
    assert queue.dequeue() == "fourth"
    
    # Queue should now be empty
    assert queue.is_empty() == True