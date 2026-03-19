"""Tests for the hello_world module."""

import sys
from io import StringIO
from unittest.mock import patch

import hello_world


class TestMain:
    """Tests for the main() function."""

    def test_main_prints_hello_world(self, capsys):
        """Test that main() prints 'Hello, World!' to stdout."""
        hello_world.main()
        captured = capsys.readouterr()
        assert captured.out == "Hello, World!\n"
        assert captured.err == ""

    def test_main_output_ends_with_newline(self, capsys):
        """Test that output ends with a newline."""
        hello_world.main()
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_main_no_stderr_output(self, capsys):
        """Test that main() produces no stderr output."""
        hello_world.main()
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_main_exact_output(self, capsys):
        """Test that main() produces exactly the expected output."""
        hello_world.main()
        captured = capsys.readouterr()
        expected = "Hello, World!\n"
        assert captured.out == expected


class TestModuleExecution:
    """Tests for module execution."""

    def test_main_can_be_called_multiple_times(self, capsys):
        """Test that main() can be called multiple times without issues."""
        hello_world.main()
        captured1 = capsys.readouterr()
        
        hello_world.main()
        captured2 = capsys.readouterr()
        
        assert captured1.out == "Hello, World!\n"
        assert captured2.out == "Hello, World!\n"

    def test_module_has_main_function(self):
        """Test that the module has a main function."""
        assert hasattr(hello_world, "main")
        assert callable(hello_world.main)
