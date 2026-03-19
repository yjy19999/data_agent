import pytest
from linked_list import LinkedList

class TestLinkedList:
    
    def setup_method(self):
        self.ll = LinkedList()
    
    def test_insert_into_empty_list(self):
        self.ll.insert(1)
        assert self.ll.search(1) == True
        assert self.ll.search(2) == False
    
    def test_insert_multiple_elements(self):
        self.ll.insert(1)
        self.ll.insert(2)
        self.ll.insert(3)
        
        # Should be in reverse order of insertion since we're inserting at head
        assert self.ll.search(1) == True
        assert self.ll.search(2) == True
        assert self.ll.search(3) == True
    
    def test_delete_from_empty_list(self):
        result = self.ll.delete(1)
        assert result == False
    
    def test_delete_head_element(self):
        self.ll.insert(1)
        self.ll.insert(2)
        
        # List should be 2 -> 1
        result = self.ll.delete(2)
        assert result == True
        assert self.ll.search(2) == False
        assert self.ll.search(1) == True
    
    def test_delete_middle_element(self):
        self.ll.insert(1)
        self.ll.insert(2)
        self.ll.insert(3)
        
        # List should be 3 -> 2 -> 1
        result = self.ll.delete(2)
        assert result == True
        assert self.ll.search(3) == True
        assert self.ll.search(2) == False
        assert self.ll.search(1) == True
    
    def test_delete_nonexistent_element(self):
        self.ll.insert(1)
        self.ll.insert(2)
        
        result = self.ll.delete(3)
        assert result == False
        assert self.ll.search(1) == True
        assert self.ll.search(2) == True
    
    def test_search_empty_list(self):
        assert self.ll.search(1) == False
    
    def test_search_nonexistent_element(self):
        self.ll.insert(1)
        self.ll.insert(2)
        
        assert self.ll.search(3) == False

if __name__ == '__main__':
    pytest.main()