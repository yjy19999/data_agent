## Files to Modify / Create
- `lru_cache.py` - Implement the LRUCache class with get, put, and configurable max size
- `test_lru_cache.py` - Create comprehensive tests for the LRUCache implementation
- `README.md` - Document usage and features of the LRU cache

## Changes per File
### lru_cache.py
- Create `LRUCache` class with constructor accepting `maxsize` parameter
- Implement `get(key)` method that returns value and raises KeyError for missing keys
- Implement `put(key, value)` method that stores key-value pairs and handles LRU eviction
- Use `collections.OrderedDict` to maintain order and achieve O(1) operations
- Handle edge cases like zero-sized cache and updating existing keys

### test_lru_cache.py
- Create test suite using pytest
- Test initialization with valid and invalid maxsize values
- Test basic put/get operations
- Test KeyError for non-existent keys
- Test LRU eviction policy
- Test updating existing keys without changing cache size
- Test proper LRU ordering maintenance

### README.md
- Document the LRUCache class usage
- Explain the methods and their parameters
- Provide usage examples

## Test Plan
- Create `test_lru_cache.py` using pytest framework
- Test cases will cover:
  - Happy path: Basic put/get operations
  - Edge cases: Empty cache, full cache, updating existing keys
  - Error cases: Invalid maxsize values, non-existent keys
  - LRU behavior: Proper eviction and ordering
- No special fixtures or helpers needed beyond standard pytest

## Execution Order
1. Implement the core LRUCache class in `lru_cache.py`
2. Create comprehensive tests in `test_lru_cache.py`
3. Run tests to verify implementation correctness
4. Create documentation in `README.md`

## Expected Risks
- Incorrectly implementing the LRU eviction mechanism
- Not achieving O(1) time complexity due to inefficient data structure choices
- Improper handling of edge cases like empty cache or updating existing keys
- Misunderstanding how LRU works (whether access in `get` should update recency)
- Off-by-one errors in eviction logic