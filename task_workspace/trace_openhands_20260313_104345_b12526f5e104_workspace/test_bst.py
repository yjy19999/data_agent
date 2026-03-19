import unittest
from bst import BinarySearchTree

class TestBinarySearchTree(unittest.TestCase):
    def setUp(self):
        self.bst = BinarySearchTree()

    def test_insert_and_search(self):
        # Test inserting and searching for values
        self.bst.insert(5)
        self.bst.insert(3)
        self.bst.insert(7)
        self.bst.insert(1)
        self.bst.insert(9)

        self.assertTrue(self.bst.search(5))
        self.assertTrue(self.bst.search(3))
        self.assertTrue(self.bst.search(7))
        self.assertTrue(self.bst.search(1))
        self.assertTrue(self.bst.search(9))
        self.assertFalse(self.bst.search(4))
        self.assertFalse(self.bst.search(8))

    def test_insert_duplicate(self):
        # Test that inserting duplicate values doesn't break the tree
        self.bst.insert(5)
        self.bst.insert(3)
        self.bst.insert(5)  # Duplicate insert
        self.bst.insert(7)
        self.bst.insert(3)  # Another duplicate

        self.assertTrue(self.bst.search(5))
        self.assertTrue(self.bst.search(3))
        self.assertTrue(self.bst.search(7))
        self.assertFalse(self.bst.search(4))

    def test_in_order_traversal(self):
        # Test in-order traversal produces sorted list
        values = [5, 3, 7, 1, 9, 4, 6, 8, 2]
        for value in values:
            self.bst.insert(value)

        expected = sorted(values)
        self.assertEqual(self.bst.in_order_traversal(), expected)

    def test_empty_tree(self):
        # Test behavior of empty tree
        self.assertFalse(self.bst.search(5))
        self.assertEqual(self.bst.in_order_traversal(), [])

    def test_single_node(self):
        # Test tree with a single node
        self.bst.insert(42)
        self.assertTrue(self.bst.search(42))
        self.assertEqual(self.bst.in_order_traversal(), [42])

if __name__ == '__main__':
    unittest.main()