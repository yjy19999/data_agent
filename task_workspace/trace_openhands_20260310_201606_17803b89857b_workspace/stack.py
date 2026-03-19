"""A simple stack implementation using a list."""


class Stack:
    """A simple stack data structure with push, pop, and peek methods."""

    def __init__(self):
        """Initialize an empty stack."""
        self._items = []

    def push(self, item):
        """Add an item to the top of the stack.

        Args:
            item: The item to add to the stack.
        """
        self._items.append(item)

    def pop(self):
        """Remove and return the item from the top of the stack.

        Returns:
            The item at the top of the stack.

        Raises:
            IndexError: If the stack is empty.
        """
        if self.is_empty():
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self):
        """Return the item at the top of the stack without removing it.

        Returns:
            The item at the top of the stack.

        Raises:
            IndexError: If the stack is empty.
        """
        if self.is_empty():
            raise IndexError("peek from empty stack")
        return self._items[-1]

    def is_empty(self):
        """Check if the stack is empty.

        Returns:
            True if the stack is empty, False otherwise.
        """
        return len(self._items) == 0

    def size(self):
        """Return the number of items in the stack.

        Returns:
            The number of items in the stack.
        """
        return len(self._items)

    def __len__(self):
        """Return the number of items in the stack.

        Returns:
            The number of items in the stack.
        """
        return len(self._items)

    def __repr__(self):
        """Return a string representation of the stack.

        Returns:
            A string representation of the stack.
        """
        return f"Stack({self._items})"
