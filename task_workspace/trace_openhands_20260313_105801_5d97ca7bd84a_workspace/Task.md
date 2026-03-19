## Task Goal
Create a simple LRU (Least Recently Used) cache class that supports basic operations: `get`, `put`, and allows configuration of maximum cache size.

## Inputs and Outputs
### Inputs
- `maxsize`: An integer representing the maximum number of items the cache can hold.
- For `put(key, value)`:
  - `key`: Hashable object used as the key.
  - `value`: Any object to store in the cache.
- For `get(key)`:
  - `key`: Hashable object used to retrieve the value.

### Outputs
- `get(key)`: Returns the value associated with the key if present, otherwise raises KeyError or returns a default (implementation choice).
- `put(key, value)`: Stores the key-value pair in the cache. May evict the least recently used item if the cache is at capacity.
- Internally maintains order of usage for eviction policy.

## Constraints
- Language: Python
- Should use standard library only (no external dependencies)
- Time complexity for both `get` and `put` operations should be O(1) on average
- Must properly handle edge cases such as zero-sized cache, duplicate keys, etc.
- Follow common Python conventions and idioms

## Modification Scope
### Files to Create
- `lru_cache.py`: Contains the LRUCache class implementation

### Classes/Functions Required
- `LRUCache` class with:
  - Constructor accepting `maxsize`
  - `get(key)` method
  - `put(key, value)` method
  - Optional helper methods for internal logic (e.g., `_evict`)

### Complexity Estimate
Medium – Requires understanding of data structures (likely OrderedDict or custom doubly-linked list with hash map) to achieve O(1) performance.

## Risks
- Incorrectly implementing the LRU eviction mechanism leading to wrong items being removed
- Not achieving O(1) time complexity due to inefficient data structure choices
- Handling of edge cases like empty cache, full cache, updating existing keys
- Misunderstanding how LRU works (e.g., whether access in `get` should update recency)

## Success Criteria
- Implementation passes all basic functionality tests including:
  - Putting and getting values correctly
  - Evicting least recently used items when over capacity
  - Updating existing keys without changing cache size
  - Proper behavior when maxsize is set to 0 or 1
- Code is well-documented and readable
- Time complexity of operations meets requirement