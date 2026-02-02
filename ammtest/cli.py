"""
ammtest CLI - Test runner for safety-critical systems.

Usage:
    ammtest run <path>        Run tests and generate reports
    ammtest run tests/ -v     Run with verbose output
"""
import subprocess
import sys
from pathlib import Path


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

    print("=" * 60)
    print("ammtest - Running tests")
    print("=" * 60)
    print(f"Reports directory: {Path('reports').absolute()}")
    print()
    sys.stdout.flush()

    # Build pytest command with plugins and live logging
    pytest_args = [
        "pytest",
        "-p", "ammtest.fixtures",
        "-p", "ammtest.reporter",
        "--log-cli-level=INFO",
        "--log-cli-format=[%(asctime)s.%(msecs)03d] %(levelname)-8s %(message)s",
        "--log-cli-date-format=%H:%M:%S",
        "--log-format=[%(asctime)s.%(msecs)03d] %(levelname)-8s %(message)s (%(filename)s:%(lineno)d)",
        "--log-date-format=%H:%M:%S",
    ]
    pytest_args.extend(args)

    # Run pytest (reporter generates reports live)
    result = subprocess.run(pytest_args)

    print()
    print("=" * 60)
    if result.returncode == 0:
        print("Result: ALL TESTS PASSED")
    else:
        print("Result: SOME TESTS FAILED")
    print("=" * 60)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
