"""The @ammtest decorator: marks a function as a test and attaches its trace data.

There is no manual version field: each report identifies the exact test that ran
by the SHA-256 of its file and the git commit, which cannot drift.
"""

from dataclasses import dataclass

META_ATTR = "__ammtest__"


@dataclass(frozen=True)
class Metadata:
    description: str
    requirements: dict[str, str]  # requirement id -> baseline


def ammtest(*, description: str = "", requirements: dict[str, str] | None = None):
    """Mark a function as an ammtest test case.

    @ammtest(
        description="Brake engages on request",
        requirements={"REQ-1416": "A", "REQ-1418": "B"},  # id -> baseline
    )
    def test_brake(sut): ...
    """
    if not isinstance(description, str):
        raise TypeError("@ammtest: description must be a string")
    reqs = {} if requirements is None else requirements
    if not isinstance(reqs, dict):
        raise TypeError(
            "@ammtest: requirements must be a dict {requirement_id: baseline}, "
            f"e.g. {{'REQ-1416': 'A'}}; got {type(reqs).__name__}"
        )
    for req, baseline in reqs.items():
        if not isinstance(req, str) or not req.strip() or not isinstance(baseline, str):
            raise TypeError(
                f"@ammtest: requirement ids and baselines must be strings, got {req!r}: {baseline!r}"
            )
    meta = Metadata(description, dict(reqs))

    def decorator(func):
        setattr(func, META_ATTR, meta)
        return func

    return decorator
