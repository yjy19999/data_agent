## Task Goal
Create a simple queue data structure implementation in Python with basic operations: enqueue (add item), dequeue (remove item), and peek (view front item without removing).

## Inputs and Outputs
- **Inputs**: 
  - Enqueue method accepts any Python object to be added to the queue
  - Dequeue and peek methods take no arguments
- **Outputs**:
  - Enqueue method returns nothing (None)
  - Dequeue method returns the removed item from front of queue
  - Peek method returns the front item without removing it
  - Appropriate exceptions for error conditions (e.g., dequeue/peek on empty queue)

## Constraints
- Implementation must be in Python
- Use standard Python features (no external libraries)
- Follow common queue semantics (FIFO - First In, First Out)
- Handle edge cases appropriately (empty queue operations)

## Modification Scope
- Create a single file `queue.py` containing the Queue class
- Implement three public methods: `enqueue(item)`, `dequeue()`, and `peek()`
- Include appropriate error handling
- Small complexity - basic data structure implementation

## Risks
- Not properly handling empty queue conditions
- Incorrect FIFO behavior implementation
- Not raising appropriate exceptions when needed
- Memory inefficiency if using inappropriate underlying data structure

## Success Criteria
- Queue class implements all three required methods correctly
- FIFO behavior is maintained
- Empty queue conditions are handled with appropriate exceptions
- Code includes docstrings and is well-documented
- Unit tests cover normal operation and edge cases