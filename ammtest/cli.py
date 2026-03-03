"""
ammtest CLI - Test runner for safety-critical systems.

Usage:
    ammtest run <path>        Run tests and generate reports
    ammtest run tests/ -v     Run with verbose output
"""

import sys

import pytest


def main():
    """Main entry point for ammtest CLI."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "run":
        run_tests(sys.argv[2:])
    elif command in ("--help", "-h"):
        print_usage()
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


def print_usage():
    """Print CLI usage information."""
    print("ammtest - Test framework for safety-critical systems")
    print()
    print("Usage:")
    print("  ammtest run <path> [options]    Run tests and generate reports")
    print()
    print("Options:")
    print("  -v, --verbose                   Verbose output")
    print("  --ammtest-config=<path>         Config file (default: config/config.json)")
    print()
    print("Examples:")
    print("  ammtest run tests/")
    print("  ammtest run tests/ --ammtest-config=my_config.json")


def run_tests(args):
    """Run pytest with live report generation."""
    if not args:
        print("Error: No test path specified")
        print("Usage: ammtest run <path>")
        sys.exit(1)

    # Build pytest args with plugins and live logging
    pytest_args = [
        "-p", "ammtest.config",
        "-p", "ammtest.reporter",
        "--log-cli-level=INFO",
        "--log-cli-format=%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        "--log-cli-date-format=%H:%M:%S",
        "--log-level=INFO",
        "--log-format=%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        "--log-date-format=%H:%M:%S",
        "--show-capture=no",
    ]
    pytest_args.extend(args)

    # Run pytest in-process (enables debugger breakpoints)
    returncode = pytest.main(pytest_args)

    sys.exit(returncode)


if __name__ == "__main__":
    main()
