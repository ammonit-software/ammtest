class AmmioError(Exception):
    """Base exception for ammio communication errors."""

    pass


class VariableNotFoundError(AmmioError):
    """Raised when var_id doesn't exist in ammio."""

    pass


class VariableTypeError(AmmioError):
    """Raised when value type doesn't match variable definition."""

    pass


class AmmioConnectionError(AmmioError):
    """Raised when ammio service is unreachable."""

    pass
