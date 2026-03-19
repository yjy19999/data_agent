"""
Additional edge case tests for the LRUCache implementation.
These tests focus on boundary conditions and unusual scenarios.
"""
import pytest
from lru_cache import LRUCache


def test_empty_cache():
    """Test behavior of an empty cache"""
    cache = LRUCache(1)
    
    # Getting from empty cache should raise KeyError
    with pytest.raises(KeyError):
        cache.get('nonexistent')
    
    # Cache should be empty
    assert len(cache.cache) == 0


def test_single_item_cache():
    """Test behavior with maxsize=1"""
    cache = LRUCache(1)
    
    # Add one item
    cache.put('a', 1)
    assert cache.get('a') == 1
    assert len(cache.cache) == 1
    
    # Add another item - should evict first
    cache.put('b', 2)
    assert cache.get('b') == 2
    assert len(cache.cache) == 1
    
    # First item should be gone
    with pytest.raises(KeyError):
        cache.get('a')


def test_cache_full_capacity():
    """Test behavior when cache is at full capacity"""
    cache = LRUCache(3)
    
    # Fill cache to capacity
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    # Verify cache is full
    assert len(cache.cache) == 3
    
    # Access middle item to make it MRU
    assert cache.get('b') == 2
    
    # Add new item - should evict LRU item ('a')
    cache.put('d', 4)
    
    # Verify state
    assert len(cache.cache) == 3
    assert cache.get('b') == 2
    assert cache.get('c') == 3
    assert cache.get('d') == 4
    
    # 'a' should be evicted
    with pytest.raises(KeyError):
        cache.get('a')


def test_repeated_access():
    """Test repeated access to same key"""
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    # Access 'a' multiple times
    assert cache.get('a') == 1
    assert cache.get('a') == 1
    assert cache.get('a') == 1
    
    # Add new item - 'b' should be evicted (not 'a')
    cache.put('d', 4)
    
    assert cache.get('a') == 1  # Still there
    assert cache.get('c') == 3  # Still there
    assert cache.get('d') == 4  # New item
    
    # 'b' should be evicted
    with pytest.raises(KeyError):
        cache.get('b')


def test_update_does_not_change_size():
    """Test that updating existing key doesn't change cache size"""
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    initial_size = len(cache.cache)
    
    # Update existing keys
    cache.put('a', 10)
    cache.put('b', 20)
    cache.put('c', 30)
    
    # Size should remain the same
    assert len(cache.cache) == initial_size
    
    # Values should be updated
    assert cache.get('a') == 10
    assert cache.get('b') == 20
    assert cache.get('c') == 30


def test_lru_after_multiple_operations():
    """Test LRU behavior after complex sequence of operations"""
    cache = LRUCache(4)
    
    # Sequence of operations
    cache.put('a', 1)  # a
    cache.put('b', 2)  # a, b
    cache.put('c', 3)  # a, b, c
    cache.get('a')     # b, c, a (a is now MRU)
    cache.put('d', 4)  # b, c, a, d
    cache.get('c')     # b, a, d, c (c is now MRU)
    cache.put('e', 5)  # a, d, c, e (b is evicted)
    
    # Check final state
    assert cache.get('a') == 1
    assert cache.get('c') == 3
    assert cache.get('d') == 4
    assert cache.get('e') == 5
    
    # 'b' should be evicted
    with pytest.raises(KeyError):
        cache.get('b')