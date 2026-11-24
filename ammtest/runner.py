"""Discovery, execution and evidence reports.

Exit codes: 0 all tests passed, 1 a test failed or errored, 2 the run could not
be completed (collection error, no tests, ammio unreachable or lost, Ctrl+C).
"""

import getpass
import hashlib
import importlib.util
import inspect
import json
import os
import platform
import re
import socket
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .client import AmmioClient, AmmioConnectionError
from .decorator import META_ATTR, Metadata
from .sut import Failure, Sut

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
_W = 80


class CollectionError(Exception):
    """Tests could not be collected; nothing is run."""


# --- discovery ---------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    id: str  # "sub/TC_001.py::test_brake"
    rel: Path  # file path relative to the tests root
    func: Callable
    meta: Metadata
    sha256: str  # of the test file, as executed


def discover(path: str | Path) -> list[Case]:
    """Collect every @ammtest function under `path` (a file or a folder).

    In folders, files and folders whose name starts with "." or "_" are skipped
    (use `_helpers.py` for shared code). Files are taken in sorted order,
    tests in definition order.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise CollectionError(f"path not found: {path}")
    root = path if path.is_dir() else path.parent
    if path.is_file():
        files = [path]
    else:
        files = sorted(
            f for f in path.rglob("*.py")
            if not any(part.startswith((".", "_")) for part in f.relative_to(root).parts)
        )
    cases = []
    for file in files:
        cases += _collect(file, root)
    return cases


def _collect(file: Path, root: Path) -> list[Case]:
    rel = file.relative_to(root)
    for folder in (str(root), str(file.parent)):  # lets tests import their helpers
        if folder not in sys.path:
            sys.path.insert(0, folder)

    name = "ammtest_suite_" + re.sub(r"\W", "_", rel.with_suffix("").as_posix())
    source = file.read_bytes()
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(name, None)
        raise CollectionError(f"cannot import {rel.as_posix()}:\n{''.join(traceback.format_exception(e))}") from e

    digest = hashlib.sha256(source).hexdigest()
    cases = []
    for obj in vars(module).values():
        meta = getattr(obj, META_ATTR, None)
        if not (inspect.isfunction(obj) and isinstance(meta, Metadata) and obj.__module__ == name):
            continue
        case_id = f"{rel.as_posix()}::{obj.__name__}"
        nparams = len(inspect.signature(obj).parameters)
        if nparams != 1:
            raise CollectionError(f"{case_id}: a test takes exactly one argument (sut), it takes {nparams}")
        cases.append(Case(case_id, rel, obj, meta, digest))
    return cases


# --- output ------------------------------------------------------------------


class _C:
    RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
    GREEN, RED, YELLOW = "\033[92m", "\033[91m", "\033[93m"


_STYLES = {
    "pass": _C.GREEN,
    "fail": _C.RED,
    "PASS": _C.GREEN + _C.BOLD,
    "FAIL": _C.RED + _C.BOLD,
    "ERROR": _C.YELLOW + _C.BOLD,
    "bold": _C.BOLD,
    "dim": _C.DIM,
}


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


class _Out:
    """Writes each line plain to the report file and (optionally colored) to the terminal."""

    def __init__(self, file=None, color: bool = False):
        self.file = file
        self.color = color

    def line(self, text: str = "", style: str = "") -> None:
        if self.file is not None:
            self.file.write(text + "\n")
            self.file.flush()
        if self.color and style:
            text = f"{_STYLES[style]}{text}{_C.RESET}"
        print(text, flush=True)


def _kv(label: str, value: object) -> str:
    return f"  {label + ':':<16}{value}"


def _req_lines(reqs: dict[str, str]) -> list[str]:
    if not reqs:
        return [_kv("Requirements", "(none)")]
    width = max(map(len, reqs))
    lines = [f"{req:<{width}}  [{baseline or '-'}]" for req, baseline in reqs.items()]
    return [_kv("Requirements", lines[0])] + [" " * 18 + line for line in lines[1:]]


# --- execution ---------------------------------------------------------------


@dataclass
class _Outcome:
    case: Case
    status: str  # PASS | FAIL | ERROR
    started: datetime
    duration: float
    checks_passed: int
    checks_failed: int
    report: Path
    abort: str | None = None


def _context(endpoint: str) -> dict:
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return {
        "ammtest": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "user": user,
        "host": socket.gethostname(),
        "endpoint": endpoint,
    }


_PKG_DIR = Path(__file__).resolve().parent


def _format_exception(e: BaseException) -> str:
    """Traceback showing only user code: ammtest's own frames are dropped."""
    top = traceback.TracebackException.from_exception(e)
    te, seen = top, set()
    while te is not None and id(te) not in seen:  # also the chained causes
        seen.add(id(te))
        frames = [f for f in te.stack if Path(f.filename).resolve().parent != _PKG_DIR]
        te.stack = traceback.StackSummary.from_list(frames)
        te = te.__cause__ or te.__context__
    return "".join(top.format()).rstrip()


def _run_one(case: Case, client: AmmioClient, run_dir: Path, ctx: dict, color: bool) -> _Outcome:
    rel_report = case.rel.parent / f"{case.rel.stem}.{case.func.__name__}.txt"
    report = run_dir / rel_report
    report.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    with report.open("w", encoding="utf-8") as f:
        out = _Out(f, color)
        sep, dash = "=" * _W, "-" * _W
        out.line(sep, "dim")
        out.line(f"{'AMMTEST EXECUTION REPORT':^{_W}}".rstrip(), "bold")
        out.line(sep, "dim")
        out.line(_kv("Test", case.id))
        out.line(_kv("Description", case.meta.description or "(none)"))
        out.line(_kv("Version", case.meta.version or "(none)"))
        for line in _req_lines(case.meta.requirements):
            out.line(line)
        out.line(_kv("File SHA-256", case.sha256))
        out.line(dash, "dim")
        out.line(_kv("Started", started.strftime("%Y-%m-%d %H:%M:%S")))
        out.line(_kv("Executed by", ctx["user"]))
        out.line(_kv("Host", ctx["host"]))
        out.line(_kv("Endpoint", ctx["endpoint"]))
        out.line(_kv("Tool", f"ammtest {ctx['ammtest']}, Python {ctx['python']}, {ctx['platform']}"))
        out.line(sep, "dim")
        out.line()
        out.line("--- LOG ---", "bold")
        out.line()

        t0 = time.monotonic()

        def log(text: str, style: str = "") -> None:
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            elapsed = f"+{time.monotonic() - t0:.3f}s"
            out.line(f"{stamp} {elapsed:>10}  {text}", style)

        sut = Sut(client, log)
        status, error, abort = "PASS", None, None
        try:
            case.func(sut)
        except AssertionError as e:
            status, error = "FAIL", _format_exception(e)
        except AmmioConnectionError as e:
            status, error, abort = "ERROR", _format_exception(e), f"connection to ammio lost: {e}"
        except KeyboardInterrupt:
            status, error, abort = "ERROR", "interrupted by user", "interrupted by user"
        except Exception as e:
            status, error = "ERROR", _format_exception(e)
        duration = time.monotonic() - t0
        if status == "PASS" and sut.failures:
            status = "FAIL"

        out.line()
        out.line(sep, "dim")
        out.line("--- RESULT ---", "bold")
        out.line(_kv("Status", status), status)
        out.line(_kv("Duration", f"{duration:.3f}s"))
        out.line(_kv("Checks", f"{sut.passed} passed, {len(sut.failures)} failed"))
        _write_failures(out, sut.failures)
        if error:
            out.line()
            out.line("--- EXCEPTION ---", "fail")
            for line in error.splitlines():
                out.line(line, "fail")
        out.line(sep, "dim")
        out.line()

    return _Outcome(case, status, started, duration, sut.passed, len(sut.failures), rel_report, abort)


def _write_failures(out: _Out, failures: list[Failure]) -> None:
    if not failures:
        return
    out.line()
    out.line("--- CHECK FAILURES ---", "fail")
    for i, fail in enumerate(failures, 1):
        out.line(f"  [{i}] {fail.message}", "fail")
        out.line(f"      {fail.file}:{fail.line}  {fail.source}", "fail")


def _new_run_dir(results: Path, now: datetime) -> Path:
    base = results / now.strftime("%Y-%m-%d_%H-%M-%S")
    candidate, n = base, 1
    while True:
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            n += 1
            candidate = base.with_name(f"{base.name}_{n}")


def run(path: str | Path, endpoint: str, results: str | Path = "results") -> int:
    """Discover and run every test under `path`. Returns the process exit code."""
    cases = discover(path)
    if not cases:
        raise CollectionError(f"no @ammtest tests found in {path}")

    ctx = _context(endpoint)
    color = _use_color()
    started = datetime.now()
    outcomes: list[_Outcome] = []
    aborted = None

    with AmmioClient(endpoint) as client:
        run_dir = _new_run_dir(Path(results), started)
        for case in cases:
            outcome = _run_one(case, client, run_dir, ctx, color)
            outcomes.append(outcome)
            if outcome.abort:
                aborted = outcome.abort
                break

    not_run = [c.id for c in cases[len(outcomes):]]
    _write_summary(run_dir, ctx, started, datetime.now(), outcomes, not_run, aborted)
    _print_summary(_Out(color=color), run_dir, outcomes, not_run, aborted)

    if aborted:
        return EXIT_ERROR
    return EXIT_PASS if all(o.status == "PASS" for o in outcomes) else EXIT_FAIL


# --- summary -----------------------------------------------------------------


def _totals(outcomes: list[_Outcome], not_run: list[str]) -> dict:
    count = lambda s: sum(o.status == s for o in outcomes)  # noqa: E731
    return {
        "tests": len(outcomes) + len(not_run),
        "passed": count("PASS"),
        "failed": count("FAIL"),
        "errors": count("ERROR"),
        "not_run": len(not_run),
    }


def _write_summary(run_dir, ctx, started, finished, outcomes, not_run, aborted) -> None:
    totals = _totals(outcomes, not_run)
    overall = "ERROR" if aborted else ("PASS" if totals["passed"] == totals["tests"] else "FAIL")

    data = {
        **ctx,
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "status": overall,
        "aborted": aborted,
        "totals": totals,
        "tests": [
            {
                "id": o.case.id,
                "status": o.status,
                "version": o.case.meta.version,
                "description": o.case.meta.description,
                "requirements": o.case.meta.requirements,
                "file_sha256": o.case.sha256,
                "started": o.started.isoformat(timespec="milliseconds"),
                "duration_s": round(o.duration, 3),
                "checks_passed": o.checks_passed,
                "checks_failed": o.checks_failed,
                "report": o.report.as_posix(),
            }
            for o in outcomes
        ],
        "not_run": not_run,
    }
    (run_dir / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    sep, dash = "=" * _W, "-" * _W
    lines = [
        sep,
        f"{'AMMTEST RUN SUMMARY':^{_W}}".rstrip(),
        sep,
        _kv("Started", data["started"].replace("T", " ")),
        _kv("Finished", data["finished"].replace("T", " ")),
        _kv("Executed by", ctx["user"]),
        _kv("Host", ctx["host"]),
        _kv("Endpoint", ctx["endpoint"]),
        _kv("Tool", f"ammtest {ctx['ammtest']}, Python {ctx['python']}, {ctx['platform']}"),
        dash,
    ]
    lines += [f"  {o.status:<7}{o.duration:8.3f}s  {o.case.id}" for o in outcomes]
    lines += [f"  {'NOT RUN':<7}{'':>9}  {case_id}" for case_id in not_run]
    lines += [dash, _kv("Status", overall)]
    lines += [_kv(k.replace("_", " ").capitalize(), v) for k, v in totals.items()]
    if aborted:
        lines.append(_kv("Aborted", aborted))
    lines.append(sep)
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(out: _Out, run_dir, outcomes, not_run, aborted) -> None:
    out.line("=" * 60, "dim")
    for o in outcomes:
        out.line(f"{o.status:<7}{o.duration:8.3f}s  {o.case.id}", o.status)
    for case_id in not_run:
        out.line(f"{'NOT RUN':<7}{'':>9}  {case_id}", "dim")
    out.line("-" * 60, "dim")
    t = _totals(outcomes, not_run)
    text = f"{t['tests']} tests: {t['passed']} passed, {t['failed']} failed, {t['errors']} errors"
    if t["not_run"]:
        text += f", {t['not_run']} not run"
    out.line(text, "PASS" if t["passed"] == t["tests"] else "FAIL")
    if aborted:
        out.line(f"Run aborted: {aborted}", "ERROR")
    out.line(f"Results: {run_dir}", "dim")
