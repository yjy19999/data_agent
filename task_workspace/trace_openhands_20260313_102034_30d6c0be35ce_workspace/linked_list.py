class Node:
    def __init__(self, data):
        self.data = data
        self.next = None

class LinkedList:
    def __init__(self):
        self.head = None

    def insert(self, data):
        """Insert a new node at the beginning of the list."""
        new_node = Node(data)
        new_node.next = self.head
        self.head = new_node

    def delete(self, data):
        """Delete the first occurrence of a node with given data."""
        # If list is empty
        if not self.head:
            return False
        
        # If head needs to be deleted
        if self.head.data == data:
            self.head = self.head.next
            return True
        
        # Find the node to delete
        current = self.head
        while current.next:
            if current.next.data == data:
                current.next = current.next.next
                return True
            current = current.next
        
        return False  # Data not found

    def search(self, data):
        """Search for a node with given data. Return True if found, False otherwise."""
        current = self.head
        while current:
            if current.data == data:
                return True
            current = current.next
        return False