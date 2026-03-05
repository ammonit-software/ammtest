"""
ammtest CLI - Test runner for safety-critical systems.

Usage:
    ammtest run <path>                          Run all tests in folder
    ammtest run <path> --ammtest-config=<path>  With explicit config
"""

import json
import sys


def main():
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
    print("ammtest - Test framework for safety-critical systems")
    print()
    print("Usage:")
    print("  ammtest run <path> [options]")
    print()
    print("Options:")
    print("  --ammtest-config=<path>    Config file (default: config/config.json)")
    print()
    print("Examples:")
    print("  ammtest run examples/")
    print("  ammtest run examples/ --ammtest-config=config/config.json")


def run_tests(args):
    if not args:
        print("Error: No test path specified")
        print("Usage: ammtest run <path>")
        sys.exit(1)

    test_path = args[0]
    config_path = "config/config.json"

    for arg in args[1:]:
        if arg.startswith("--ammtest-config="):
            config_path = arg.split("=", 1)[1]

    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config: {e}")
        sys.exit(1)

    from .runner import run
    sys.exit(run(test_path, config, config_path))


if __name__ == "__main__":
    main()
