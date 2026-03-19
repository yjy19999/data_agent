## Relevant Files
- `bst.py` - Main implementation of the binary search tree
- `test_bst.py` - Unit tests for the binary search tree
- `Task.md` - Original task specification

## Dependency Graph
```
test_bst.py
    ↓
bst.py
```
The test module depends on the implementation module.

## Candidate Modification Points
- `bst.py` - This is the primary file where the BST implementation resides and may need enhancements or bug fixes.
- `test_bst.py` - May need additional test cases or modifications if the implementation changes.

## Risky / Sensitive Modules
- `bst.py` - Core logic module. Changes here affect all functionality. Key risks include:
  - Maintaining BST properties during insertions
  - Handling edge cases (duplicates, empty tree)
  - Recursive implementation correctness