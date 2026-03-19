# Binary Search Tree Implementation

A simple and efficient implementation of a Binary Search Tree (BST) data structure in Python with essential operations for inserting nodes, searching for values, and performing in-order traversal.

## Features

- Insert values while maintaining BST properties
- Search for values efficiently
- In-order traversal to get values in sorted order
- Handles edge cases (empty tree, duplicates, etc.)

## Installation

No external dependencies required. This implementation uses only Python standard library.

## Usage

```python
from bst import BinarySearchTree

# Create a new BST
bst = BinarySearchTree()

# Insert values
bst.insert(5)
bst.insert(3)
bst.insert(7)
bst.insert(1)
bst.insert(9)

# Search for values
print(bst.search(5))  # True
print(bst.search(4))  # False

# Get sorted list of values
print(bst.in_order_traversal())  # [1, 3, 5, 7, 9]
```

## API Reference

### `BinarySearchTree` Class

#### `__init__()`
Creates a new empty binary search tree.

#### `insert(value)`
Inserts a new value into the tree while maintaining BST properties.
- **Parameters**: `value` (int) - The value to insert
- **Returns**: None

#### `search(value)`
Searches for a value in the tree.
- **Parameters**: `value` (int) - The value to search for
- **Returns**: bool - True if value exists in the tree, False otherwise

#### `in_order_traversal()`
Performs in-order traversal of the tree.
- **Parameters**: None
- **Returns**: list - Values in sorted order

### `Node` Class

Internal class representing a tree node. Not intended for direct use.

#### `__init__(value)`
Creates a new node with the given value.
- **Parameters**: `value` (int) - The value to store in the node