import pytest
from lru_cache import LRUCache


def test_init():
    cache = LRUCache(3)
    assert cache.maxsize == 3
    
    with pytest.raises(ValueError):
        LRUCache(0)
        
    with pytest.raises(ValueError):
        LRUCache(-1)


def test_put_and_get():
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    assert cache.get('a') == 1
    assert cache.get('b') == 2
    assert cache.get('c') == 3


def test_get_nonexistent_key():
    cache = LRUCache(3)
    cache.put('a', 1)
    
    with pytest.raises(KeyError):
        cache.get('b')


def test_eviction():
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    # Access 'a' to make it recently used
    cache.get('a')
    
    # Adding 'd' should evict 'b' (least recently used)
    cache.put('d', 4)
    
    assert cache.get('a') == 1
    assert cache.get('c') == 3
    assert cache.get('d') == 4
    
    with pytest.raises(KeyError):
        cache.get('b')


def test_update_existing_key():
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    # Update 'b'
    cache.put('b', 20)
    
    # Add 'd', which should evict 'a'
    cache.put('d', 4)
    
    assert cache.get('b') == 20
    assert cache.get('c') == 3
    assert cache.get('d') == 4
    
    with pytest.raises(KeyError):
        cache.get('a')


def test_lru_order():
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    
    # Access 'a' and then 'b'
    cache.get('a')
    cache.get('b')
    
    # Add 'd', which should evict 'c'
    cache.put('d', 4)
    
    assert cache.get('a') == 1
    assert cache.get('b') == 2
    assert cache.get('d') == 4
    
    with pytest.raises(KeyError):
        cache.get('c')


def test_maxsize_one():
    """Test behavior when maxsize is 1"""
    cache = LRUCache(1)
    
    cache.put('a', 1)
    assert cache.get('a') == 1
    
    # Adding another item should evict 'a'
    cache.put('b', 2)
    assert cache.get('b') == 2
    
    with pytest.raises(KeyError):
        cache.get('a')


def test_same_key_update():
    """Test updating the same key multiple times"""
    cache = LRUCache(3)
    
    cache.put('a', 1)
    cache.put('a', 2)
    cache.put('a', 3)
    
    assert cache.get('a') == 3
    assert len(cache.cache) == 1


def test_mixed_operations():
    """Test a sequence of mixed put/get operations"""
    cache = LRUCache(2)
    
    cache.put('a', 1)
    cache.put('b', 2)
    
    assert cache.get('a') == 1  # Access 'a'
    
    cache.put('c', 3)  # Should evict 'b'
    
    assert cache.get('c') == 3
    assert cache.get('a') == 1
    
    with pytest.raises(KeyError):
        cache.get('b')


def test_different_key_types():
    """Test that the cache works with different types of keys"""
    cache = LRUCache(3)
    
    cache.put(1, 'number')
    cache.put('key', 'string')
    cache.put((1, 2), 'tuple')
    
    assert cache.get(1) == 'number'
    assert cache.get('key') == 'string'
    assert cache.get((1, 2)) == 'tuple'


def test_different_value_types():
    """Test that the cache works with different types of values"""
    cache = LRUCache(3)
    
    cache.put('list', [1, 2, 3])
    cache.put('dict', {'a': 1})
    cache.put('none', None)
    
    assert cache.get('list') == [1, 2, 3]
    assert cache.get('dict') == {'a': 1}
    assert cache.get('none') is None