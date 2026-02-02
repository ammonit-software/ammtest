class AmmioError(Exception):
    """Base exception for ammio communication errors."""
    pass


class SignalNotFoundError(AmmioError):
    """Raised when var_id doesn't exist in ammio."""
    pass


class SignalTypeError(AmmioError):
    """Raised when value type doesn't match signal definition."""
    pass


class AmmioConnectionError(AmmioError):
    """Raised when ammio service is unreachable."""
    pass
