"""Tests for the Stack class."""

import pytest
from stack import Stack


class TestStackInit:
    """Tests for Stack initialization."""

    def test_init_creates_empty_stack(self):
        """Test that a new stack is empty."""
        stack = Stack()
        assert stack.is_empty()
        assert stack.size() == 0
        assert len(stack) == 0

    def test_repr_empty_stack(self):
        """Test string representation of empty stack."""
        stack = Stack()
        assert repr(stack) == "Stack([])"


class TestStackPush:
    """Tests for the push method."""

    def test_push_single_item(self):
        """Test pushing a single item."""
        stack = Stack()
        stack.push(1)
        assert stack.size() == 1
        assert not stack.is_empty()

    def test_push_multiple_items(self):
        """Test pushing multiple items."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.push(3)
        assert stack.size() == 3

    def test_push_different_types(self):
        """Test pushing items of different types."""
        stack = Stack()
        stack.push(1)
        stack.push("hello")
        stack.push([1, 2, 3])
        stack.push({"key": "value"})
        assert stack.size() == 4

    def test_push_none(self):
        """Test pushing None as an item."""
        stack = Stack()
        stack.push(None)
        assert stack.size() == 1
        assert stack.peek() is None


class TestStackPop:
    """Tests for the pop method."""

    def test_pop_single_item(self):
        """Test popping a single item."""
        stack = Stack()
        stack.push(1)
        item = stack.pop()
        assert item == 1
        assert stack.is_empty()

    def test_pop_returns_last_pushed(self):
        """Test that pop returns items in LIFO order."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.push(3)
        assert stack.pop() == 3
        assert stack.pop() == 2
        assert stack.pop() == 1

    def test_pop_empty_stack_raises_error(self):
        """Test that popping an empty stack raises IndexError."""
        stack = Stack()
        with pytest.raises(IndexError) as exc_info:
            stack.pop()
        assert "pop from empty stack" in str(exc_info.value)

    def test_pop_after_multiple_operations(self):
        """Test pop after various push/pop operations."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.pop()
        stack.push(3)
        assert stack.pop() == 3
        assert stack.pop() == 1


class TestStackPeek:
    """Tests for the peek method."""

    def test_peek_single_item(self):
        """Test peeking at a single item."""
        stack = Stack()
        stack.push(1)
        assert stack.peek() == 1
        assert stack.size() == 1  # Item should still be there

    def test_peek_does_not_remove_item(self):
        """Test that peek does not remove the item."""
        stack = Stack()
        stack.push(1)
        stack.peek()
        assert stack.size() == 1
        assert stack.peek() == 1

    def test_peek_returns_top_item(self):
        """Test that peek returns the most recently pushed item."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.push(3)
        assert stack.peek() == 3

    def test_peek_empty_stack_raises_error(self):
        """Test that peeking an empty stack raises IndexError."""
        stack = Stack()
        with pytest.raises(IndexError) as exc_info:
            stack.peek()
        assert "peek from empty stack" in str(exc_info.value)


class TestStackIsEmpty:
    """Tests for the is_empty method."""

    def test_is_empty_on_new_stack(self):
        """Test that a new stack is empty."""
        stack = Stack()
        assert stack.is_empty() is True

    def test_is_empty_after_push(self):
        """Test that stack is not empty after push."""
        stack = Stack()
        stack.push(1)
        assert stack.is_empty() is False

    def test_is_empty_after_pop_all(self):
        """Test that stack is empty after popping all items."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.pop()
        stack.pop()
        assert stack.is_empty() is True


class TestStackSize:
    """Tests for the size method and __len__."""

    def test_size_after_push(self):
        """Test size after pushing items."""
        stack = Stack()
        stack.push(1)
        assert stack.size() == 1
        stack.push(2)
        assert stack.size() == 2

    def test_size_after_pop(self):
        """Test size after popping items."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.pop()
        assert stack.size() == 1

    def test_len_method(self):
        """Test that len() works on stack."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.push(3)
        assert len(stack) == 3

    def test_size_matches_len(self):
        """Test that size() and len() return the same value."""
        stack = Stack()
        for i in range(5):
            stack.push(i)
        assert stack.size() == len(stack)


class TestStackRepr:
    """Tests for __repr__ method."""

    def test_repr_with_items(self):
        """Test string representation with items."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        assert repr(stack) == "Stack([1, 2])"

    def test_repr_after_pop(self):
        """Test string representation after pop."""
        stack = Stack()
        stack.push(1)
        stack.push(2)
        stack.pop()
        assert repr(stack) == "Stack([1])"


class TestStackIntegration:
    """Integration tests for Stack."""

    def test_push_pop_alternating(self):
        """Test alternating push and pop operations."""
        stack = Stack()
        stack.push(1)
        assert stack.pop() == 1
        stack.push(2)
        stack.push(3)
        assert stack.pop() == 3
        assert stack.pop() == 2
        assert stack.is_empty()

    def test_large_stack(self):
        """Test stack with many items."""
        stack = Stack()
        for i in range(1000):
            stack.push(i)
        assert stack.size() == 1000
        assert stack.peek() == 999
        for i in range(999, -1, -1):
            assert stack.pop() == i
        assert stack.is_empty()

    def test_stack_with_complex_objects(self):
        """Test stack with complex objects."""
        stack = Stack()
        obj1 = {"a": 1, "b": 2}
        obj2 = [1, 2, [3, 4]]
        obj3 = (1, 2, 3)
        stack.push(obj1)
        stack.push(obj2)
        stack.push(obj3)
        assert stack.pop() is obj3
        assert stack.pop() is obj2
        assert stack.pop() is obj1
