def ammtest(version="", description="", requirements=None):
    """
    Marks a function as an ammtest test case.

    Args:
        version: Test version string
        description: What this test verifies
        requirements: List of requirement IDs covered (e.g. ["REQ-001", "REQ-002"])
    """
    def decorator(func):
        func._ammtest_meta = {
            "version": version,
            "description": description,
            "requirements": requirements or [],
        }
        return func
    return decorator
