"""
pytest plugin for ammtest report generation.

Generates .txt report per test file (after completion).
"""

import re
from pathlib import Path

import pytest

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

REPORTS_DIR = Path("reports")
_results = {}


def pytest_configure(config):  # noqa: ARG001
    REPORTS_DIR.mkdir(exist_ok=True)
    _results.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Collect test results and logs."""
    outcome = yield
    report = outcome.get_result()

    if call.when == "call":
        test_file = item.fspath.purebasename
        if test_file not in _results:
            _results[test_file] = {"path": item.fspath, "tests": []}

        # Capture logs from report sections
        logs = ""
        for section_name, section_content in report.sections:
            if "log" in section_name.lower():
                logs += section_content

        _results[test_file]["tests"].append({
            "name": item.name,
            "status": "PASSED" if report.passed else "FAILED",
            "duration": report.duration,
            "error": str(report.longrepr) if report.failed else None,
            "logs": logs.strip(),
        })


def pytest_runtest_teardown(item, nextitem):
    """Generate .txt report when test file completes."""
    current = item.fspath.purebasename
    next_file = nextitem.fspath.purebasename if nextitem else None

    if current != next_file and current in _results:
        _write_report(current)


def _write_report(test_file):
    """Write .txt report for a test file."""
    data = _results[test_file]
    report_path = REPORTS_DIR / f"{test_file}.txt"

    with open(report_path, "w") as f:
        f.write("=" * 50 + "\n")
        f.write(f"TEST: {data['path'].basename}\n")
        f.write("=" * 50 + "\n")

        docstring = _extract_docstring(data["path"])
        if docstring:
            f.write(docstring + "\n")
        f.write("-" * 50 + "\n\n")

        for t in data["tests"]:
            f.write(f"{t['status']}: {t['name']} ({t['duration']:.3f}s)\n")
            if t["logs"]:
                logs = _ANSI_ESCAPE.sub("", t["logs"])
                for line in logs.split("\n"):
                    f.write(f"  {line}\n")
            if t["error"]:
                f.write(f"  Error:\n{t['error']}\n")
            f.write("\n")

        passed = sum(1 for t in data["tests"] if t["status"] == "PASSED")
        failed = len(data["tests"]) - passed
        f.write("-" * 50 + "\n")
        f.write(f"SUMMARY: {passed} passed, {failed} failed\n")


def _extract_docstring(filepath):
    with open(filepath) as f:
        content = f.read()
        if content.startswith('"""'):
            end = content.find('"""', 3)
            if end != -1:
                return content[3:end].strip()
    return ""
