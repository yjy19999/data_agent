import pytest
from priority_queue import PriorityQueue


def test_push_and_pop():
    pq = PriorityQueue()
    pq.push("task1", 3)
    pq.push("task2", 1)
    pq.push("task3", 2)
    
    # Should return items in priority order (lowest priority value first)
    assert pq.pop() == "task2"
    assert pq.pop() == "task3"
    assert pq.pop() == "task1"


def test_peek():
    pq = PriorityQueue()
    pq.push("task1", 3)
    pq.push("task2", 1)
    
    # Peek should return the highest priority item without removing it
    assert pq.peek() == "task2"
    assert pq.size() == 2  # Size should remain unchanged


def test_empty_queue():
    pq = PriorityQueue()
    
    # Both pop and peek should raise IndexError for empty queue
    with pytest.raises(IndexError):
        pq.pop()
        
    with pytest.raises(IndexError):
        pq.peek()


def test_same_priorities():
    pq = PriorityQueue()
    pq.push("task1", 2)
    pq.push("task2", 2)
    pq.push("task3", 1)
    
    # Items with same priority should be returned in insertion order
    assert pq.pop() == "task3"  # Priority 1
    assert pq.pop() == "task1"  # Inserted before task2
    assert pq.pop() == "task2"


def test_is_empty_and_size():
    pq = PriorityQueue()
    assert pq.is_empty()
    assert pq.size() == 0
    
    pq.push("task1", 1)
    assert not pq.is_empty()
    assert pq.size() == 1
    
    pq.pop()
    assert pq.is_empty()
    assert pq.size() == 0