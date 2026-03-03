"""
pytest plugin for ammtest configuration.

Loads config from --ammtest-config and exposes CONFIG_PATH for test files.
"""

import json
from pathlib import Path

CONFIG_PATH = None
CONFIG = None


def get_config(config):
    _config_path = config.getoption("--ammtest-config", default="config/config.json")
    with open(_config_path) as f:
        _config = json.load(f)
    return _config_path, _config


def pytest_addoption(parser):
    parser.addoption(
        "--ammtest-config",
        default="config/config.json",
        help="Path to ammtest config file",
    )


def pytest_configure(config):
    global CONFIG_PATH, CONFIG

    CONFIG_PATH, CONFIG = get_config(config)
