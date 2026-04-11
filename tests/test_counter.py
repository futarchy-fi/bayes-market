import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from counter import Counter


def test_default_initial_value():
    c = Counter()
    assert c.value == 0


def test_custom_initial_value():
    c = Counter(10)
    assert c.value == 10


def test_negative_initial_value():
    c = Counter(-5)
    assert c.value == -5


def test_invalid_initial_value():
    with pytest.raises(TypeError, match="integer"):
        Counter(3.5)


def test_increment():
    c = Counter()
    assert c.increment() == 1
    assert c.increment() == 2
    assert c.value == 2


def test_increment_by_amount():
    c = Counter()
    assert c.increment(5) == 5
    assert c.increment(3) == 8


def test_increment_invalid_amount():
    c = Counter()
    with pytest.raises(ValueError, match="positive integer"):
        c.increment(0)
    with pytest.raises(ValueError, match="positive integer"):
        c.increment(-1)


def test_decrement():
    c = Counter(10)
    assert c.decrement() == 9
    assert c.decrement() == 8
    assert c.value == 8


def test_decrement_by_amount():
    c = Counter(10)
    assert c.decrement(3) == 7
    assert c.decrement(5) == 2


def test_decrement_below_zero():
    c = Counter(1)
    assert c.decrement(5) == -4


def test_decrement_invalid_amount():
    c = Counter()
    with pytest.raises(ValueError, match="positive integer"):
        c.decrement(0)


def test_reset():
    c = Counter(42)
    assert c.reset() == 0
    assert c.value == 0


def test_repr():
    assert repr(Counter()) == "Counter(0)"
    assert repr(Counter(7)) == "Counter(7)"
