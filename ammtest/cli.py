"""
ammtest CLI - Test runner for safety-critical systems.

Usage:
    ammtest run <path> --endpoint=<url>                     Run all tests
    ammtest run <path> --endpoint=<url> --results=<path>    With custom results folder
    ammtest run <path> --endpoint=<url> --tests-root=<path> With explicit tests root
    ammtest vars --endpoint=<url>                           List all variables in ammio
    ammtest vars --endpoint=<url> --output=<path>           Write variable list to file
    ammtest trace-tests <path>                              List test cases and their requirements
    ammtest trace-tests <path> --output=<path>              Write trace to file
    ammtest trace-reqs <path> --reqs=<csv> --col=<n>            List requirements and their test coverage
    ammtest trace-reqs <path> --reqs=<csv> --col=<n> --skip-header --output=<path>
"""

import sys


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "run":
        run_tests(sys.argv[2:])
    elif command == "vars":
        list_vars(sys.argv[2:])
    elif command == "trace-tests":
        trace_tests(sys.argv[2:])
    elif command == "trace-reqs":
        trace_reqs(sys.argv[2:])
    elif command in ("--help", "-h"):
        print_usage()
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


def print_usage():
    print(
        "ammtest - Python test framework for critical-software systems. Write, run, and trace system-level tests against any System Under Test (SUT)."
    )
    print()
    print("Usage:")
    print("  ammtest run <path> --endpoint=<url> [options]")
    print("  ammtest vars --endpoint=<url> [options]")
    print("  ammtest trace-tests <path> [options]")
    print()
    print("Options (run):")
    print("  --endpoint=<url>      ammio endpoint (e.g. tcp://127.0.0.1:5555)")
    print("  --results=<path>      Results folder (default: results)")
    print("  --tests-root=<path>   Tests root for relative paths (default: <path>)")
    print()
    print("Options (vars):")
    print("  --endpoint=<url>      ammio endpoint")
    print("  --output=<path>       Write variable list to file")
    print()
    print("Options (trace-tests):")
    print("  --output=<path>       Write trace to file")
    print()
    print("Examples:")
    print("  ammtest run tests/ --endpoint=tcp://127.0.0.1:5555")
    print("  ammtest run tests/ --endpoint=tcp://127.0.0.1:5555 --results=out/")
    print("  ammtest vars --endpoint=tcp://127.0.0.1:5555")
    print("  ammtest vars --endpoint=tcp://127.0.0.1:5555 --output=vars.txt")
    print("  ammtest trace-tests tests/")
    print("  ammtest trace-tests tests/ --output=trace.txt")
    print("  ammtest trace-reqs tests/ --reqs=requirements.csv --col=1 --skip-header")
    print("  ammtest trace-reqs tests/ --reqs=requirements.csv --col=1 --skip-header --output=coverage.txt")


def run_tests(args):
    if not args:
        print("Error: No test path specified")
        print("Usage: ammtest run <path> --endpoint=<url>")
        sys.exit(1)

    test_path = args[0]
    endpoint = None
    results = "results"
    tests_root = ""

    for arg in args[1:]:
        if arg.startswith("--endpoint="):
            endpoint = arg.split("=", 1)[1]
        elif arg.startswith("--results="):
            results = arg.split("=", 1)[1]
        elif arg.startswith("--tests-root="):
            tests_root = arg.split("=", 1)[1]

    if not endpoint:
        print("Error: --endpoint is required")
        print("Usage: ammtest run <path> --endpoint=<url>")
        sys.exit(1)

    from .runner import run

    sys.exit(run(test_path, endpoint, results, tests_root))


def list_vars(args):
    endpoint = None
    output_path = None

    for arg in args:
        if arg.startswith("--endpoint="):
            endpoint = arg.split("=", 1)[1]
        elif arg.startswith("--output="):
            output_path = arg.split("=", 1)[1]

    if not endpoint:
        print("Error: --endpoint is required")
        print("Usage: ammtest vars --endpoint=<url>")
        sys.exit(1)

    from .ammio import AmmioClient

    client = AmmioClient(endpoint)
    try:
        vars_list = client.list_vars()
    finally:
        client.close()

    if not vars_list:
        print(f"No variables in ammio var_table at {endpoint}.")
        print("Is ammio running and fully initialized?")
        return

    col_id   = max(max(len(v["var_id"]) for v in vars_list), len("Variable"))
    col_type = max(max(len(str(v.get("type", ""))) for v in vars_list), len("Type"))
    col_dir  = max(max(len(str(v.get("dir",  ""))) for v in vars_list), len("Dir"))

    lines = [
        f"  {'Variable':<{col_id}}  {'Type':<{col_type}}  Dir",
        f"  {'-' * col_id}  {'-' * col_type}  {'-' * col_dir}",
    ]
    for v in vars_list:
        lines.append(f"  {v['var_id']:<{col_id}}  {str(v.get('type', '')):<{col_type}}  {v.get('dir', '')}")
    lines.append("")
    lines.append(f"  {len(vars_list)} variable(s)")

    output = "\n".join(lines)
    print(output)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output + "\n")
        print(f"\n  Written to {output_path}")


def trace_tests(args):
    if not args:
        print("Error: No test path specified")
        print("Usage: ammtest trace-tests <path>")
        sys.exit(1)

    test_path = args[0]
    output_path = None

    for arg in args[1:]:
        if arg.startswith("--output="):
            output_path = arg.split("=", 1)[1]

    from pathlib import Path
    from .runner import _discover

    base = Path(test_path).resolve()
    tests = _discover(base, base if base.is_dir() else base.parent)

    if not tests:
        print(f"No tests found in {test_path}")
        return

    col_test = max(
        max(len(f"{p.stem}::{fn.__name__}") for p, fn in tests),
        len("Test"),
    )

    lines = [
        f"  {'Test':<{col_test}}  Requirements",
        f"  {'-' * col_test}  {'-' * 40}",
    ]
    no_reqs = []
    for rel_path, func in tests:
        name = f"{rel_path.stem}::{func.__name__}"
        reqs = func._ammtest_meta.get("requirements", [])
        if reqs:
            req_str = ", ".join(r['req'] for r in reqs)
        else:
            req_str = "(none)"
            no_reqs.append(name)
        lines.append(f"  {name:<{col_test}}  {req_str}")

    lines.append("")
    lines.append(f"  {len(tests)} test(s)  |  {len(no_reqs)} without requirements")
    if no_reqs:
        lines.append("")
        lines.append("  Tests with no requirements:")
        for name in no_reqs:
            lines.append(f"    {name}")

    output = "\n".join(lines)
    print(output)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output + "\n")
        print(f"\n  Written to {output_path}")


def trace_reqs(args):
    if not args:
        print("Error: No test path specified")
        print("Usage: ammtest trace-reqs <path> --reqs=<csv> --col=<column>")
        sys.exit(1)

    test_path = args[0]
    reqs_path = None
    col = None
    skip_header = False
    delimiter = ","
    output_path = None

    for arg in args[1:]:
        if arg.startswith("--reqs="):
            reqs_path = arg.split("=", 1)[1]
        elif arg.startswith("--col="):
            col = arg.split("=", 1)[1]
        elif arg == "--skip-header":
            skip_header = True
        elif arg.startswith("--delimiter="):
            delimiter = arg.split("=", 1)[1]
        elif arg.startswith("--output="):
            output_path = arg.split("=", 1)[1]

    if not reqs_path:
        print("Error: --reqs is required")
        sys.exit(1)
    if col is None:
        print("Error: --col is required (1-based column number)")
        sys.exit(1)

    try:
        col_idx = int(col) - 1  # convert 1-based to 0-based
        if col_idx < 0:
            raise ValueError
    except ValueError:
        print(f"Error: --col must be a positive integer, got '{col}'")
        sys.exit(1)

    import csv
    from pathlib import Path
    from .runner import _discover

    if len(delimiter) != 1:
        print(f"Error: --delimiter must be a single character (e.g. --delimiter=\";\")")
        sys.exit(1)

    try:
        with open(reqs_path, newline="") as f:
            rows = list(csv.reader(f, delimiter=delimiter))
    except FileNotFoundError:
        print(f"Error: Requirements file not found: {reqs_path}")
        sys.exit(1)

    if skip_header:
        rows = rows[1:]

    req_ids = [
        row[col_idx] for row in rows
        if len(row) > col_idx and row[col_idx].strip()
    ]

    if not req_ids:
        print("No requirements found. Check --col and --skip-header.")
        return

    # Build req_id -> [test names] map from test metadata
    base = Path(test_path).resolve()
    tests = _discover(base, base if base.is_dir() else base.parent)

    coverage = {}  # req_id -> list of test names
    for rel_path, func in tests:
        name = f"{rel_path.stem}::{func.__name__}"
        for r in func._ammtest_meta.get("requirements", []):
            req_id = r["req"]
            coverage.setdefault(req_id, []).append(name)

    col_req = max(max(len(r) for r in req_ids), len("Requirement"))
    not_covered = [r for r in req_ids if r not in coverage]

    lines = [
        f"  {'Requirement':<{col_req}}  Tests",
        f"  {'-' * col_req}  {'-' * 40}",
    ]
    for req_id in req_ids:
        tests_str = ", ".join(coverage[req_id]) if req_id in coverage else "(not covered)"
        lines.append(f"  {req_id:<{col_req}}  {tests_str}")

    lines.append("")
    lines.append(f"  {len(req_ids)} requirement(s)  |  {len(not_covered)} not covered")
    if not_covered:
        lines.append("")
        lines.append("  Requirements with no test coverage:")
        for req_id in not_covered:
            lines.append(f"    {req_id}")

    output = "\n".join(lines)
    print(output)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output + "\n")
        print(f"\n  Written to {output_path}")


if __name__ == "__main__":
    main()
