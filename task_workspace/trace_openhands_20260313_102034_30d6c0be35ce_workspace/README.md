# Linked List Implementation

A simple singly linked list data structure implementation in Python with basic operations: insert, delete, and search.

## Description

This module provides a straightforward implementation of a singly linked list with essential operations. It includes two main components:
- `Node`: Represents individual elements in the linked list
- `LinkedList`: Manages the collection of nodes with methods for insertion, deletion, and searching

## Installation

No external dependencies are required. This implementation uses only standard Python features.

## Usage

```python
# Import the LinkedList class
from linked_list import LinkedList

# Create a new linked list
ll = LinkedList()

# Insert elements
ll.insert(10)
ll.insert(20)
ll.insert(30)

# Search for elements
found = ll.search(20)  # Returns True
not_found = ll.search(40)  # Returns False

# Delete elements
deleted = ll.delete(20)  # Returns True if element was found and deleted
not_deleted = ll.delete(50)  # Returns False if element was not found
```

## API Reference

### `LinkedList` Class

#### `__init__()`
Creates an empty linked list.

#### `insert(data)`
Inserts a new node with the specified data at the beginning of the list.

**Parameters:**
- `data`: The data to be stored in the new node

**Returns:**
- None

#### `delete(data)`
Deletes the first occurrence of a node with the specified data.

**Parameters:**
- `data`: The data to be deleted from the list

**Returns:**
- `bool`: True if the element was found and deleted, False otherwise

#### `search(data)`
Searches for a node with the specified data in the list.

**Parameters:**
- `data`: The data to search for

**Returns:**
- `bool`: True if the element was found, False otherwise

### `Node` Class

#### `__init__(data)`
Creates a new node with the specified data.

**Parameters:**
- `data`: The data to be stored in the node

#### Attributes:
- `data`: The data stored in the node
- `next`: Reference to the next node in the list (None if this is the last node)