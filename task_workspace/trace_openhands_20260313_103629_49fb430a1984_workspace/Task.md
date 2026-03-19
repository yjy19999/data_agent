## Task Goal
Create a simple priority queue class that supports push, pop, and peek operations, returning items based on their priority order.

## Inputs and Outputs
- **Inputs**: 
  - Items to be added to the queue via `push`, each with an associated priority value
  - Priority values used to determine ordering (typically numeric, where lower values indicate higher priority)
- **Outputs**:
  - `pop()` returns and removes the highest-priority item
  - `peek()` returns the highest-priority item without removing it
  - `push(item, priority)` adds an item to the queue based on its priority

## Constraints
- Implementation must be in Python
- Must use standard library only (no external dependencies)
- Priorities should support comparison (e.g., integers or floats)
- Time complexity should be reasonable for basic operations (ideally O(log n) for push/pop)

## Modification Scope
- Create one file: `priority_queue.py`
- Implement one class: `PriorityQueue`
- Required methods: `push(item, priority)`, `pop()`, `peek()`
- Complexity: Small to Medium

## Risks
- Handling of equal priorities (which item comes first?)
- Empty queue behavior (should raise exceptions or return None?)
- Memory usage if many items are pushed but not popped
- Thread safety (not required per spec, but worth noting)

## Success Criteria
- Class implements all three methods correctly
- Items are returned in correct priority order
- Unit tests cover normal operation, edge cases (empty queue), and various priority scenarios
- Code is clean, readable, and well-documented