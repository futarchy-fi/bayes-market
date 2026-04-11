import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from math_utils import (
    add, subtract, multiply, divide,
    factorial, is_prime, gcd, fibonacci,
    mean, median, clamp,
)


# --- Arithmetic ---

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_subtract():
    assert subtract(5, 3) == 2
    assert subtract(0, 7) == -7


def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(-2, 5) == -10
    assert multiply(0, 100) == 0


def test_divide():
    assert divide(10, 2) == 5.0
    assert divide(7, 2) == 3.5
    assert divide(-6, 3) == -2.0


def test_divide_by_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1, 0)


# --- Factorial ---

def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
    assert factorial(10) == 3628800


def test_factorial_negative():
    with pytest.raises(ValueError):
        factorial(-1)


def test_factorial_non_integer():
    with pytest.raises(ValueError):
        factorial(3.5)


# --- Prime ---

def test_is_prime():
    assert is_prime(2) is True
    assert is_prime(3) is True
    assert is_prime(5) is True
    assert is_prime(7) is True
    assert is_prime(11) is True
    assert is_prime(13) is True


def test_is_not_prime():
    assert is_prime(0) is False
    assert is_prime(1) is False
    assert is_prime(4) is False
    assert is_prime(9) is False
    assert is_prime(15) is False
    assert is_prime(-3) is False


# --- GCD ---

def test_gcd():
    assert gcd(12, 8) == 4
    assert gcd(7, 13) == 1
    assert gcd(0, 5) == 5
    assert gcd(100, 75) == 25


def test_gcd_negative():
    assert gcd(-12, 8) == 4
    assert gcd(12, -8) == 4


# --- Fibonacci ---

def test_fibonacci():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1
    assert fibonacci(2) == 1
    assert fibonacci(5) == 5
    assert fibonacci(10) == 55


def test_fibonacci_negative():
    with pytest.raises(ValueError):
        fibonacci(-1)


def test_fibonacci_non_integer():
    with pytest.raises(ValueError):
        fibonacci(2.5)


# --- Mean ---

def test_mean():
    assert mean([1, 2, 3, 4, 5]) == 3.0
    assert mean([10]) == 10.0
    assert mean([2, 4]) == 3.0


def test_mean_empty():
    with pytest.raises(ValueError, match="empty"):
        mean([])


# --- Median ---

def test_median_odd():
    assert median([3, 1, 2]) == 2
    assert median([5]) == 5


def test_median_even():
    assert median([1, 2, 3, 4]) == 2.5
    assert median([10, 20]) == 15.0


def test_median_empty():
    with pytest.raises(ValueError, match="empty"):
        median([])


# --- Clamp ---

def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_clamp_invalid_range():
    with pytest.raises(ValueError, match="low must be <= high"):
        clamp(5, 10, 0)
