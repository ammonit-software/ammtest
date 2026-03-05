class AmmioError(Exception):
    """Base exception for ammio errors."""
    pass


class AmmioConnectionError(AmmioError):
    """Raised when ammio service is unreachable."""
    pass


class _CheckFailures(AssertionError):
    """Internal: carries collected check failures from th.finalize() to the runner."""
    def __init__(self, failures: list):
        self.failures = failures
        super().__init__(f"{len(failures)} check(s) failed")
