import abc

INF = float("inf")


class BaseConstraint(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def apply_to(self, value):
        raise NotImplementedError


class NoConstraint(BaseConstraint):
    def apply_to(self, value):
        return value


class InclusiveConstraint(BaseConstraint):
    __slots__ = ("low", "high")

    def __init__(self, *, low=-INF, high=INF):
        self.low = low
        self.high = high

    def apply_to(self, value):
        return min(max(self.low, value), self.high)


class BooleanConstraint(BaseConstraint):
    def apply_to(self, value):
        return bool(value)


class ConstraintedValue:
    __slots__ = ("_val", "_constraint")

    def __init__(self, value, constraint=NoConstraint()):
        self._constraint = constraint
        self._val = value

    @property
    def value(self):
        return self._val

    @value.setter
    def value(self, new_val):
        self._val = self.constraint.apply_to(new_val)

    @property
    def constraint(self):
        return self._constraint

    @constraint.setter
    def constraint(self, new_constraint):
        self._constraint = new_constraint
        self.value = self.value  # apply new constraint

    @constraint.deleter
    def constraint(self):
        self.constraint = NoConstraint()


class ConstraintedPosition:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = ConstraintedValue(x)
        self.y = ConstraintedValue(y)

    def __str__(self):
        return "(x={}, y={})".format(self.x.value, self.y.value)
