import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from greeting import greet


def test_greet_with_name():
    assert greet("Alice") == "Hello, Alice!"


def test_greet_without_name():
    assert greet() == "Hello, World!"


def test_greet_with_empty_string():
    assert greet("") == "Hello, !"
