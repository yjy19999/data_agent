# LRU Cache Implementation

This module provides a simple LRU (Least Recently Used) cache implementation using Python's `collections.OrderedDict`.

## Description

An LRU cache automatically evicts the least recently used items when it reaches its maximum capacity. This implementation provides O(1) average time complexity for both `get` and `put` operations.

## Installation

No installation required. This module uses only Python standard library components.

Dependencies:
- Python 3.7+
- `collections.OrderedDict` (standard library)

## Usage

```python
from lru_cache import LRUCache

# Create a cache with maximum size of 3
cache = LRUCache(3)

# Put key-value pairs into the cache
cache.put('key1', 'value1')
cache.put('key2', 'value2')
cache.put('key3', 'value3')

# Get values from the cache
value = cache.get('key1')  # Returns 'value1'

# If the cache is full, the least recently used item will be evicted
# when adding a new item
cache.put('key4', 'value4')  # This may evict an item
```

## API Reference

### `LRUCache(maxsize)`
Initializes the LRU cache with a specified maximum size.

**Parameters:**
- `maxsize` (int): The maximum number of items the cache can hold. Must be greater than 0.

**Raises:**
- `ValueError`: If `maxsize` is less than or equal to 0.

### `get(key)`
Retrieves the value associated with the given key from the cache.

**Parameters:**
- `key`: The key whose associated value is to be returned.

**Returns:**
- The value associated with the key.

**Raises:**
- `KeyError`: If the key is not present in the cache.

### `put(key, value)`
Inserts or updates a key-value pair in the cache.

**Parameters:**
- `key`: The key to insert or update.
- `value`: The value to associate with the key.

If the cache is at maximum capacity, the least recently used item will be evicted to make space for the new item. If the key already exists, its value will be updated and it will become the most recently used item.

## Known Limitations

- Keys must be hashable (as required by dictionary-like data structures)
- No thread-safety guarantees
- No persistence mechanism (cache contents are lost when object is destroyed)