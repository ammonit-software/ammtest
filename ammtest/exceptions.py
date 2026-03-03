class AmmioError(Exception):
    """Base exception for ammio errors."""

    pass


class AmmioConnectionError(AmmioError):
    """Raised when ammio service is unreachable."""

    pass
