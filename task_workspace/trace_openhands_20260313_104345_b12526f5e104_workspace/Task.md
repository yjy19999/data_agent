## Task Goal
Implement a simple binary search tree (BST) data structure with basic operations: inserting nodes, searching for values, and performing an in-order traversal.

## Inputs and Outputs
- **Inputs**: Integer values to insert or search for in the BST.
- **Outputs**:
  - Insert: Modifies the tree structure by adding a new node.
  - Search: Returns a boolean indicating whether a value exists in the tree.
  - In-order Traversal: Returns a list of values in sorted order.

## Constraints
- Language: Python
- No external libraries allowed.
- Implementation should adhere to standard BST properties (left child < parent < right child).
- Code should handle edge cases such as duplicate inserts or searches in empty trees.

## Modification Scope
- **Files to create**: `bst.py`
- **Classes/Functions**:
  - `class Node`: Represents a tree node with value, left, and right attributes.
  - `class BinarySearchTree`: Contains methods for insert, search, and in-order traversal.
    - `insert(value)`
    - `search(value)`
    - `in_order_traversal()` (returns a list)
- **Complexity**: Small

## Risks
- Incorrectly handling duplicate values during insertion/search.
- Failing to maintain BST properties during insertion.
- Not properly implementing recursive traversals.
- Edge cases like inserting into an empty tree or searching in an empty tree.

## Success Criteria
- A working BST implementation that correctly handles insertions, searches, and traversals.
- Unit tests covering normal operations, duplicates, and edge cases.
- Clean, readable code with appropriate comments/docstrings.