import unittest
from queue import Queue

class TestQueue(unittest.TestCase):
    """Unit tests for the Queue class."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.queue = Queue()
    
    def test_enqueue_increases_size(self):
        """Test that enqueue increases the queue size."""
        self.assertEqual(self.queue.size(), 0)
        self.queue.enqueue(1)
        self.assertEqual(self.queue.size(), 1)
        self.queue.enqueue(2)
        self.assertEqual(self.queue.size(), 2)
    
    def test_dequeue_decreases_size(self):
        """Test that dequeue decreases the queue size."""
        self.queue.enqueue(1)
        self.queue.enqueue(2)
        self.assertEqual(self.queue.size(), 2)
        self.queue.dequeue()
        self.assertEqual(self.queue.size(), 1)
        self.queue.dequeue()
        self.assertEqual(self.queue.size(), 0)
    
    def test_fifo_order(self):
        """Test that queue follows FIFO (First In, First Out) order."""
        self.queue.enqueue(1)
        self.queue.enqueue(2)
        self.queue.enqueue(3)
        
        # First item dequeued should be the first one enqueued
        self.assertEqual(self.queue.dequeue(), 1)
        self.assertEqual(self.queue.dequeue(), 2)
        self.assertEqual(self.queue.dequeue(), 3)
    
    def test_peek_returns_front_item(self):
        """Test that peek returns the front item without removing it."""
        self.queue.enqueue(1)
        self.queue.enqueue(2)
        
        # Peek should return first item
        self.assertEqual(self.queue.peek(), 1)
        # Size should remain unchanged
        self.assertEqual(self.queue.size(), 2)
        
        # After dequeue, peek should return the new front item
        self.queue.dequeue()
        self.assertEqual(self.queue.peek(), 2)
    
    def test_peek_on_empty_queue_raises_error(self):
        """Test that peek on an empty queue raises IndexError."""
        with self.assertRaises(IndexError) as context:
            self.queue.peek()
        self.assertIn("peek from an empty queue", str(context.exception))
    
    def test_dequeue_on_empty_queue_raises_error(self):
        """Test that dequeue on an empty queue raises IndexError."""
        with self.assertRaises(IndexError) as context:
            self.queue.dequeue()
        self.assertIn("dequeue from an empty queue", str(context.exception))
    
    def test_is_empty_on_new_queue(self):
        """Test that a new queue is empty."""
        self.assertTrue(self.queue.is_empty())
    
    def test_is_empty_on_non_empty_queue(self):
        """Test that a queue with items is not empty."""
        self.queue.enqueue(1)
        self.assertFalse(self.queue.is_empty())
    
    def test_is_empty_after_dequeueing_all_items(self):
        """Test that queue is empty after dequeueing all items."""
        self.queue.enqueue(1)
        self.queue.enqueue(2)
        self.queue.dequeue()
        self.queue.dequeue()
        self.assertTrue(self.queue.is_empty())

if __name__ == '__main__':
    unittest.main()