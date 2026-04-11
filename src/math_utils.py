def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def factorial(n):
    if not isinstance(n, int) or n < 0:
        raise ValueError("Factorial requires a non-negative integer")
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def is_prime(n):
    if not isinstance(n, int) or n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def gcd(a, b):
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def fibonacci(n):
    if not isinstance(n, int) or n < 0:
        raise ValueError("Fibonacci requires a non-negative integer")
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def mean(numbers):
    if not numbers:
        raise ValueError("Cannot compute mean of empty sequence")
    return sum(numbers) / len(numbers)


def median(numbers):
    if not numbers:
        raise ValueError("Cannot compute median of empty sequence")
    sorted_nums = sorted(numbers)
    n = len(sorted_nums)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_nums[mid - 1] + sorted_nums[mid]) / 2
    return sorted_nums[mid]


def clamp(value, low, high):
    if low > high:
        raise ValueError("low must be <= high")
    return max(low, min(high, value))
