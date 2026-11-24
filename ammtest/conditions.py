"""Conditions: predicates that know how to describe themselves in a report.

A check accepts:
  - a plain value          -> equality:            sut.check("x", 1)
  - a condition            -> printable predicate: sut.check("x", between(0, 5))
  - any other callable     -> logged by its name:  sut.check("x", is_valid)
"""

from collections.abc import Callable
from typing import Any


class Condition:
    """A predicate plus the text that describes it in reports.

    Custom condition: Condition(lambda v: v % 2 == 0, "is even")
    """

    __slots__ = ("_fn", "_text")

    def __init__(self, fn: Callable[[Any], Any], text: str):
        self._fn = fn
        self._text = text

    def __call__(self, value: Any) -> bool:
        return bool(self._fn(value))

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"Condition({self._text!r})"


def eq(x: Any) -> Condition:
    return Condition(lambda v: v == x, f"== {x!r}")


def ne(x: Any) -> Condition:
    return Condition(lambda v: v != x, f"!= {x!r}")


def lt(x: Any) -> Condition:
    return Condition(lambda v: v < x, f"< {x!r}")


def le(x: Any) -> Condition:
    return Condition(lambda v: v <= x, f"<= {x!r}")


def gt(x: Any) -> Condition:
    return Condition(lambda v: v > x, f"> {x!r}")


def ge(x: Any) -> Condition:
    return Condition(lambda v: v >= x, f">= {x!r}")


def between(low: Any, high: Any) -> Condition:
    """low <= value <= high (both bounds included)."""
    if low > high:
        raise ValueError(f"between: low ({low!r}) is greater than high ({high!r})")
    return Condition(lambda v: low <= v <= high, f"in [{low!r}, {high!r}]")


def approx(x: float, tol: float) -> Condition:
    """|value - x| <= tol."""
    if tol < 0:
        raise ValueError(f"approx: tol must be >= 0, got {tol!r}")
    return Condition(lambda v: abs(v - x) <= tol, f"== {x!r} +- {tol!r}")


def as_condition(expected: Any) -> Condition:
    if isinstance(expected, Condition):
        return expected
    if callable(expected):
        return Condition(expected, getattr(expected, "__name__", repr(expected)))
    return eq(expected)
