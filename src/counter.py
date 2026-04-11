class Counter:
    def __init__(self, initial=0):
        if not isinstance(initial, int):
            raise TypeError("initial value must be an integer")
        self._value = initial

    @property
    def value(self):
        return self._value

    def increment(self, amount=1):
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("amount must be a positive integer")
        self._value += amount
        return self._value

    def decrement(self, amount=1):
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("amount must be a positive integer")
        self._value -= amount
        return self._value

    def reset(self):
        self._value = 0
        return self._value

    def __repr__(self):
        return f"Counter({self._value})"
