import pytest

from ammtest import Condition, approx, between, eq, ge, gt, le, lt, ne
from ammtest.conditions import as_condition
from ammtest.decorator import META_ATTR, ammtest


@pytest.mark.parametrize(
    "cond, text, true, false",
    [
        (eq(1), "== 1", 1, 0),
        (ne(1), "!= 1", 0, 1),
        (lt(5), "< 5", 4, 5),
        (le(5), "<= 5", 5, 6),
        (gt(5), "> 5", 6, 5),
        (ge(5), ">= 5", 5, 4),
        (between(1, 3), "in [1, 3]", 3, 4),
        (approx(3.3, 0.1), "== 3.3 +- 0.1", 3.39, 3.41),
        (Condition(lambda v: v % 2 == 0, "is even"), "is even", 2, 3),
    ],
)
def test_conditions(cond, text, true, false):
    assert str(cond) == text
    assert cond(true) is True
    assert cond(false) is False


def test_as_condition():
    def is_on(v):
        return v == 1

    assert str(as_condition(1)) == "== 1"
    assert str(as_condition(True)) == "== True"
    assert str(as_condition(is_on)) == "is_on"
    c = eq(2)
    assert as_condition(c) is c


def test_invalid_conditions():
    with pytest.raises(ValueError):
        between(3, 1)
    with pytest.raises(ValueError):
        approx(1.0, -0.1)


def test_decorator_attaches_metadata():
    @ammtest(description="d", requirements={"REQ-1": "A", "REQ-2": ""})
    def t(sut):
        pass

    meta = getattr(t, META_ATTR)
    assert (meta.description, meta.requirements) == ("d", {"REQ-1": "A", "REQ-2": ""})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"requirements": [{"req": "REQ-1", "baseline": "A"}]},
        {"requirements": {"": "A"}},
        {"requirements": {"REQ-1": 1}},
        {"description": 1},
        {"version": "1.0"},  # removed: the file hash and git commit identify the test
    ],
)
def test_decorator_rejects_bad_metadata(kwargs):
    with pytest.raises(TypeError):
        ammtest(**kwargs)


def test_decorator_is_keyword_only():
    with pytest.raises(TypeError):
        ammtest("description")
