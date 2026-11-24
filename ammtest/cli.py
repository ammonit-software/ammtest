"""ammtest command line: run, vars, trace."""

import argparse
import csv
import os
import sys

from . import __version__
from .client import AmmioClient, AmmioError
from .runner import EXIT_ERROR, EXIT_FAIL, EXIT_PASS, Case, CollectionError, discover, run
from .sut import DEFAULT_MAX_AGE

DEFAULT_ENDPOINT = "tcp://127.0.0.1:5555"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    fmt = lambda row: "  " + "  ".join(f"{str(x):<{w}}" for x, w in zip(row, widths)).rstrip()  # noqa: E731
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows])


def _cmd_run(args) -> int:
    return run(args.path, args.endpoint, args.results, args.verbose, args.max_age)


def _cmd_vars(args) -> int:
    with AmmioClient(args.endpoint) as client:
        variables = client.list_vars()
    if not variables:
        print(f"No variables in ammio at {args.endpoint}. Is ammio fully initialized?")
        return EXIT_ERROR
    rows = [[v.get("var_id", ""), v.get("type", ""), v.get("dir", "")] for v in variables]
    print(_table(["Variable", "Type", "Dir"], rows))
    print(f"\n  {len(rows)} variable(s)")
    return EXIT_PASS


def _read_requirements(path: str, col: int, delimiter: str, skip_header: bool) -> list[str]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f, delimiter=delimiter))
    except FileNotFoundError:
        raise CollectionError(f"requirements file not found: {path}") from None
    if skip_header:
        rows = rows[1:]
    ids = (row[col - 1].strip() for row in rows if len(row) >= col)
    return list(dict.fromkeys(i for i in ids if i))  # unique, file order


def _cmd_trace(args) -> int:
    cases = discover(args.path)
    if not cases:
        raise CollectionError(f"no @ammtest tests found in {args.path}")
    if args.reqs is None:
        return _trace_tests(cases)
    if args.col < 1:
        raise CollectionError(f"--col is 1-based, got {args.col}")
    if len(args.delimiter) != 1:
        raise CollectionError(f"--delimiter must be one character, got {args.delimiter!r}")
    reqs = _read_requirements(args.reqs, args.col, args.delimiter, args.skip_header)
    if not reqs:
        raise CollectionError(f"no requirement ids in column {args.col} of {args.reqs}")
    return _trace_reqs(cases, reqs)


def _trace_tests(cases: list[Case]) -> int:
    rows = [
        [c.id, ", ".join(f"{r} [{b or '-'}]" for r, b in c.meta.requirements.items()) or "(none)"]
        for c in cases
    ]
    print(_table(["Test", "Requirements"], rows))
    untraced = [c.id for c in cases if not c.meta.requirements]
    print(f"\n  {len(cases)} test(s), {len(untraced)} without requirements")
    for case_id in untraced:
        print(f"    {case_id}")
    return EXIT_FAIL if untraced else EXIT_PASS


def _trace_reqs(cases: list[Case], reqs: list[str]) -> int:
    coverage: dict[str, list[str]] = {}
    for c in cases:
        for req, baseline in c.meta.requirements.items():
            coverage.setdefault(req, []).append(f"{c.id} [{baseline or '-'}]")
    rows = [[req, ", ".join(coverage.get(req, [])) or "(not covered)"] for req in reqs]
    print(_table(["Requirement", "Tests"], rows))

    uncovered = [r for r in reqs if r not in coverage]
    known = set(reqs)
    unknown = [r for r in coverage if r not in known]
    print(f"\n  {len(reqs)} requirement(s), {len(uncovered)} not covered")
    for req in uncovered:
        print(f"    {req}")
    if unknown:
        print(f"\n  {len(unknown)} requirement(s) referenced by tests but not in the requirements file")
        for req in unknown:
            print(f"    {req}  <- {', '.join(coverage[req])}")
    return EXIT_FAIL if uncovered or unknown else EXIT_PASS


def _parser() -> argparse.ArgumentParser:
    default_endpoint = os.environ.get("AMMTEST_ENDPOINT", DEFAULT_ENDPOINT)
    endpoint_help = f"ammio endpoint (default: $AMMTEST_ENDPOINT, else {DEFAULT_ENDPOINT})"

    p = argparse.ArgumentParser(
        prog="ammtest",
        allow_abbrev=False,
        description="Write, run and trace system-level tests against any SUT through ammio.",
        epilog="exit codes: 0 pass, 1 test failed / trace gap, 2 could not run",
    )
    p.add_argument("--version", action="version", version=f"ammtest {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    r = sub.add_parser("run", allow_abbrev=False, help="run tests and write evidence reports")
    r.add_argument("path", help="test file, folder, or file::test_name")
    r.add_argument("-e", "--endpoint", default=default_endpoint, help=endpoint_help)
    r.add_argument("-r", "--results", default="results", help="results folder (default: results)")
    r.add_argument("-v", "--verbose", action="store_true", help="stream the full report to the terminal")
    r.add_argument(
        "--max-age", type=float, metavar="SECONDS",
        default=os.environ.get("AMMTEST_MAX_AGE", str(DEFAULT_MAX_AGE)),  # str: argparse validates it
        help="a SUT output not received within this time is stale and makes the test an ERROR; "
        f"0 disables the check (default: $AMMTEST_MAX_AGE, else {DEFAULT_MAX_AGE})",
    )
    r.set_defaults(func=_cmd_run)

    v = sub.add_parser("vars", allow_abbrev=False, help="list the variables ammio exposes")
    v.add_argument("-e", "--endpoint", default=default_endpoint, help=endpoint_help)
    v.set_defaults(func=_cmd_vars)

    t = sub.add_parser(
        "trace",
        allow_abbrev=False,
        help="traceability: tests -> requirements, or requirements -> tests with --reqs",
        description="Without --reqs: list each test and its requirements (fails if a test has none). "
        "With --reqs: list each requirement of the CSV and the tests covering it "
        "(fails if one is not covered or a test references an id missing from the CSV). "
        "Does not connect to ammio.",
    )
    t.add_argument("path", help="test file, folder, or file::test_name")
    t.add_argument("--reqs", metavar="CSV", help="requirements file (CSV or one id per line)")
    t.add_argument("--col", type=int, default=1, help="1-based column holding the ids (default: 1)")
    t.add_argument("--delimiter", default=",", help="CSV delimiter (default: ,)")
    t.add_argument("--skip-header", action="store_true", help="ignore the first row")
    t.set_defaults(func=_cmd_trace)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (CollectionError, AmmioError) as e:
        print(f"ammtest: error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
