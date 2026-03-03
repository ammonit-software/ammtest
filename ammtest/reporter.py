"""
pytest plugin for ammtest result generation.

Generates one .txt result per test file, mirroring the test directory structure.
"""

import logging
import re
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import pytest

from ammtest.config import get_config

logger = logging.getLogger("ammtest")

TEST_METADATA = [
    "VERSION",
    "DESCRIPTION",
    "REQUIREMENTS",
]

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_results_dir = None
_test_path = None


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    global _results_dir, _test_path

    _, CONFIG = get_config(config)
    _results_dir = Path(CONFIG["results_path"])
    _results_dir.mkdir(parents=True, exist_ok=True)

    _test_path = Path(config.args[0]) if config.args else None


def pytest_report_header(config):
    return [
        f"results: {_results_dir.absolute()}",
    ]


def pytest_runtest_setup(item):

    labels = {
        "DATE": datetime.now().strftime("%Y-%m-%d-%H:%M:%S"),
        "python VERSION": sys.version,
        "ammtest VERSION": version("ammtest"),
        "TEST": item.nodeid,
    }

    for attr in TEST_METADATA:
        value = getattr(item.module, attr, None)
        if value is not None:
            labels[attr] = value

    label_width = max(len(label) for label in labels) + 1

    for label, value in labels.items():
        logger.info(f"{label}:{' '*(label_width-len(label))}{value}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if call.when != "call":
        return

    test_file = Path(str(item.fspath))
    rel_path = _relative_path(test_file)
    result_path = _results_dir / rel_path.with_suffix(".txt")
    result_path.parent.mkdir(parents=True, exist_ok=True)

    with open(result_path, "w") as f:
        module = item.module
        for attr in TEST_METADATA:
            value = getattr(module, attr, None)
            if value is not None:
                f.write(f"{attr}: {value}\n")

        f.write(f"\nSTATUS: {'PASSED' if report.passed else 'FAILED'}\n")
        f.write(f"DURATION: {report.duration:.3f}s\n")

        logs = ""
        for section_name, section_content in report.sections:
            if "log" in section_name.lower():
                logs += section_content
        if logs.strip():
            f.write(f"\nLOGS:\n{_ANSI_ESCAPE.sub('', logs.strip())}\n")

        if report.failed:
            f.write(f"\nERROR:\n{report.longrepr}\n")


def _relative_path(test_file):
    if _test_path and _test_path.is_dir():
        try:
            return test_file.relative_to(Path.cwd() / _test_path)
        except ValueError:
            pass
    return Path(test_file.name)
