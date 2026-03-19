## Task Goal
Implement a simple singly linked list data structure in Python with basic operations: insert, delete, and search.

## Inputs and Outputs
- **Inputs**: 
  - For insert: a value to be inserted into the list
  - For delete: a value to be removed from the list
  - For search: a value to be searched in the list
- **Outputs**:
  - Insert: modifies the list by adding a new node
  - Delete: modifies the list by removing a node (if found)
  - Search: returns True/False indicating whether the value exists in the list

## Constraints
- Language: Python
- Implementation should be from scratch without using built-in data structures like lists for the core functionality
- No external libraries allowed
- Should handle basic edge cases (empty list, single element, non-existent elements)

## Modification Scope
- Create a file `linked_list.py` containing:
  - A `Node` class to represent individual elements
  - A `LinkedList` class with methods for insert, delete, and search
- Estimated complexity: small

## Risks
- Handling edge cases incorrectly (empty list operations)
- Memory management issues (though less critical in Python)
- Incorrect pointer manipulation leading to lost nodes
- Ambiguity in deletion behavior (delete first occurrence vs. all occurrences)

## Success Criteria
- Code compiles and runs without errors
- All three methods (insert, delete, search) work correctly
- Unit tests cover basic functionality and edge cases
- Implementation follows standard linked list conventions