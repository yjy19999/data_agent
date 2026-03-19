import heapq


class PriorityQueue:
    """
    A simple priority queue implementation using heapq.
    
    Items with lower priority values are retrieved first.
    """

    def __init__(self):
        """Initialize an empty priority queue."""
        self._queue = []
        self._index = 0  # Used to maintain insertion order for items with same priority

    def push(self, item, priority):
        """
        Add an item to the priority queue.
        
        Args:
            item: The item to add to the queue
            priority: The priority of the item (lower values have higher priority)
        """
        heapq.heappush(self._queue, (priority, self._index, item))
        self._index += 1

    def pop(self):
        """
        Remove and return the highest priority item from the queue.
        
        Returns:
            The item with the highest priority (lowest priority value)
            
        Raises:
            IndexError: If the queue is empty
        """
        if self.is_empty():
            raise IndexError("pop from an empty priority queue")
        priority, _, item = heapq.heappop(self._queue)
        return item

    def peek(self):
        """
        Return the highest priority item without removing it from the queue.
        
        Returns:
            The item with the highest priority (lowest priority value)
            
        Raises:
            IndexError: If the queue is empty
        """
        if self.is_empty():
            raise IndexError("peek from an empty priority queue")
        priority, _, item = self._queue[0]
        return item

    def is_empty(self):
        """
        Check if the priority queue is empty.
        
        Returns:
            bool: True if the queue is empty, False otherwise
        """
        return len(self._queue) == 0

    def size(self):
        """
        Get the number of items in the priority queue.
        
        Returns:
            int: The number of items in the queue
        """
        return len(self._queue)