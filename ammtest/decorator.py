def ammtest(version="", description="", requirements=None):
    """
    Marks a function as an ammtest test case.

    Args:
        version: Test version string
        description: What this test verifies
        requirements: List of dicts, each with 'req' and 'baseline' keys
                      e.g. [{"req": "RS-001", "baseline": "A"}]
    """
    def decorator(func):
        reqs = requirements or []
        for r in reqs:
            if not isinstance(r, dict) or "req" not in r or "baseline" not in r:
                raise ValueError(
                    f"@ammtest: each requirement must be a dict with 'req' and 'baseline' keys, got: {r!r}"
                )
        func._ammtest_meta = {
            "version": version,
            "description": description,
            "requirements": reqs,
        }
        return func
    return decorator
