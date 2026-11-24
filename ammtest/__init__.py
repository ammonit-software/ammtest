"""ammtest: minimal, traceable system-test framework for critical software."""

__version__ = "0.2.0"

from .client import AmmioClient, AmmioConnectionError, AmmioError, StaleValueError  # noqa: E402
from .conditions import Condition, approx, between, eq, ge, gt, le, lt, ne  # noqa: E402
from .decorator import ammtest  # noqa: E402
from .sut import Sut  # noqa: E402

__all__ = [
    "__version__",
    "ammtest",
    "Sut",
    "Condition",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "between",
    "approx",
    "AmmioClient",
    "AmmioError",
    "AmmioConnectionError",
    "StaleValueError",
]
