"""
pytest fixtures for ammtest.
"""

import pytest

from ammtest import AmmioClient


def pytest_addoption(parser):
    parser.addoption(
        "--ammtest-config",
        default="config/config.json",
        help="Path to ammtest config file",
    )


@pytest.fixture(scope="session")
def client(request):
    """Session-scoped AmmioClient fixture."""
    config_path = request.config.getoption("--ammtest-config")
    c = AmmioClient(config_path)
    yield c
    c.close()
