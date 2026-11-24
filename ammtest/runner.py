"""Discovery, execution and evidence reports.

Exit codes: 0 all tests passed, 1 a test failed or errored, 2 the run could not
be completed (collection error, no tests, ammio unreachable or lost, safe state
failed, Ctrl+C).
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
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .client import AmmioClient, AmmioConnectionError, AmmioError
from .decorator import META_ATTR, Metadata
from .sut import DEFAULT_MAX_AGE, Failure, Sut

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
SAFE_STATE_FILE = "_safe_state.py"
_W = 80
_PKG_DIR = Path(__file__).resolve().parent


class CollectionError(Exception):
    """Tests could not be collected; nothing is run."""


# --- discovery ---------------------------------------------------------------


@dataclass(frozen=True)
class SafeState:
    path: Path
    func: Callable
    sha256: str


@dataclass(frozen=True)
class Case:
    id: str  # "sub/TC_001.py::test_brake"
    rel: Path  # file path relative to the tests root
    path: Path  # absolute file path
    func: Callable
    meta: Metadata
    sha256: str  # of the test file, as executed
    safe_state: SafeState | None


def discover(path: str | Path) -> list[Case]:
    """Collect every @ammtest function under `path`: a file, a folder, or `file::test_name`.

    In folders, files and folders whose name starts with "." or "_" are skipped
    (use `_helpers.py` for shared code). Files are taken in sorted order,
    tests in definition order. Each test gets the nearest `_safe_state.py`
    found in its folder or any parent folder.
    """
    path, name = str(path), None
    if "::" in path:
        path, name = path.rsplit("::", 1)
    root_path = Path(path).resolve()
    if not root_path.exists():
        raise CollectionError(f"path not found: {root_path}")
    root = root_path if root_path.is_dir() else root_path.parent
    if root_path.is_file():
        files = [root_path]
    else:
        files = sorted(
            (f for f in root_path.rglob("*.py")
             if not any(part.startswith((".", "_")) for part in f.relative_to(root).parts)),
            key=lambda f: f.relative_to(root).parts,  # same order on every OS (Windows paths sort caseless)
        )
    safe_states: dict[Path, SafeState | None] = {}
    cases = []
    for file in files:
        cases += _collect(file, root, safe_states)
    if name is not None:
        cases = [c for c in cases if c.func.__name__ == name]
        if not cases:
            raise CollectionError(f"no @ammtest test named {name!r} in {path}")
    return cases


def _load_module(file: Path, label: str):
    name = "ammtest_suite_" + re.sub(r"\W", "_", label)
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(name, None)
        raise CollectionError(f"cannot import {label}:\n{''.join(traceback.format_exception(e))}") from e
    return module


def _collect(file: Path, root: Path, safe_states: dict) -> list[Case]:
    rel = file.relative_to(root)
    for folder in (str(root), str(file.parent)):  # lets tests import their helpers
        if folder not in sys.path:
            sys.path.insert(0, folder)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    module = _load_module(file, rel.with_suffix("").as_posix())
    safe_state = _find_safe_state(file.parent, safe_states)

    cases = []
    for obj in vars(module).values():
        meta = getattr(obj, META_ATTR, None)
        if not (inspect.isfunction(obj) and isinstance(meta, Metadata) and obj.__module__ == module.__name__):
            continue
        case_id = f"{rel.as_posix()}::{obj.__name__}"
        nparams = len(inspect.signature(obj).parameters)
        if nparams != 1:
            raise CollectionError(f"{case_id}: a test takes exactly one argument (sut), it takes {nparams}")
        cases.append(Case(case_id, rel, file, obj, meta, digest, safe_state))
    return cases


def _find_safe_state(folder: Path, cache: dict) -> SafeState | None:
    if folder in cache:
        return cache[folder]
    file = folder / SAFE_STATE_FILE
    if file.is_file():
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        module = _load_module(file, f"safe_state_{digest[:12]}")
        func = getattr(module, "safe_state", None)
        if not inspect.isfunction(func) or len(inspect.signature(func).parameters) != 1:
            raise CollectionError(f"{file}: must define a function `safe_state(sut)`")
        found = SafeState(file, func, digest)
    elif folder.parent != folder:
        found = _find_safe_state(folder.parent, cache)
    else:
        found = None
    cache[folder] = found
    return found


# --- environment ---------------------------------------------------------------


def _context(endpoint: str, max_age: float) -> dict:
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
        "max_value_age_s": max_age,
    }


def git_state(file: Path) -> dict | None:
    """{"commit": HEAD, "committed": file is tracked and identical to HEAD}, or None outside git."""
    def git(*args):
        return subprocess.run(["git", "-C", str(file.parent), *args], capture_output=True, text=True, timeout=10)

    try:
        head = git("rev-parse", "HEAD")
        if head.returncode != 0:
            return None
        tracked = git("ls-files", "--error-unmatch", "--", file.name).returncode == 0
        committed = tracked and git("diff", "--quiet", "HEAD", "--", file.name).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {"commit": head.stdout.strip(), "committed": committed}


def _git_text(state: dict | None) -> str:
    if state is None:
        return "(not under git)"
    return f"{state['commit']}  " + ("(committed)" if state["committed"] else "(UNCOMMITTED CHANGES)")


def _shown(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:  # other drive on Windows
        return str(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- output ------------------------------------------------------------------


class _C:
    RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
    GREEN, RED, YELLOW = "\033[92m", "\033[91m", "\033[93m"


_STYLES = {
    "pass": _C.GREEN,
    "fail": _C.RED,
    "warn": _C.YELLOW,
    "PASS": _C.GREEN + _C.BOLD,
    "FAIL": _C.RED + _C.BOLD,
    "ERROR": _C.YELLOW + _C.BOLD,
    "bold": _C.BOLD,
    "dim": _C.DIM,
}


class _Term:
    def __init__(self, color: bool):
        self.color = color

    def write(self, text: str = "", style: str = "", end: str = "\n") -> None:
        if self.color and style:
            text = f"{_STYLES[style]}{text}{_C.RESET}"
        print(text, end=end, flush=True)


class _Out:
    """One report file; every line can also be echoed live to the terminal (verbose)."""

    def __init__(self, file, echo: _Term | None):
        self.file = file
        self.echo = echo

    def line(self, text: str = "", style: str = "") -> None:
        self.file.write(text + "\n")
        self.file.flush()
        if self.echo:
            self.echo.write(text, style)

    def section(self, title: str, style: str = "bold") -> None:
        self.line()
        self.line(f"--- {title} ---", style)
        self.line()


class _Logger:
    """Timestamped log lines: wall clock + seconds since `restart()`."""

    def __init__(self, out: _Out):
        self.out = out
        self.t0 = time.monotonic()

    def restart(self) -> None:
        self.t0 = time.monotonic()

    def __call__(self, text: str, style: str = "") -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        elapsed = f"+{time.monotonic() - self.t0:.3f}s"
        self.out.line(f"{stamp} {elapsed:>10}  {text}", style)


def _kv(label: str, value: object) -> str:
    return f"  {label + ':':<16}{value}"


def _req_lines(reqs: dict[str, str]) -> list[str]:
    if not reqs:
        return [_kv("Requirements", "(none)")]
    width = max(map(len, reqs))
    lines = [f"{req:<{width}}  [{baseline or '-'}]" for req, baseline in reqs.items()]
    return [_kv("Requirements", lines[0])] + [" " * 18 + line for line in lines[1:]]


def _ctx_lines(ctx: dict, started: datetime) -> list[str]:
    return [
        _kv("Started", started.strftime("%Y-%m-%d %H:%M:%S")),
        _kv("Executed by", ctx["user"]),
        _kv("Host", ctx["host"]),
        _kv("Endpoint", ctx["endpoint"]),
        _kv("Max value age", _max_age_text(ctx["max_value_age_s"])),
        _kv("Tool", f"ammtest {ctx['ammtest']}, Python {ctx['python']}, {ctx['platform']}"),
    ]


def _max_age_text(max_age: float) -> str:
    return f"{max_age}s (older SUT outputs are an ERROR)" if max_age else "not checked"


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


def _last_line(text: str) -> str:
    return text.strip().splitlines()[-1] if text.strip() else text


# --- execution ---------------------------------------------------------------


@dataclass
class _Outcome:
    case: Case
    status: str  # PASS | FAIL | ERROR
    started: datetime
    duration: float
    checks_passed: int
    checks_failed: int
    failures: list[Failure]
    error: str | None
    report: Path  # relative to the run folder
    abort: str | None = None  # why the run stops after this test
    abort_kind: str | None = None  # "connection" | "safe_state" | "interrupt"


def _apply_safe_state(safe_state: SafeState, client: AmmioClient, log: _Logger, max_age: float) -> str | None:
    """Run safe_state(sut). Returns None on success, else what went wrong."""
    log.restart()
    sut = Sut(client, log, max_age)
    try:
        safe_state.func(sut)
    except KeyboardInterrupt:
        return "interrupted by user"
    except Exception as e:
        return _format_exception(e)
    if sut.failures:
        return f"{len(sut.failures)} check(s) failed: " + "; ".join(f.message for f in sut.failures)
    return None


def _run_one(case: Case, client: AmmioClient, run_dir: Path, ctx: dict, git: dict | None,
             term: _Term, verbose: bool) -> _Outcome:
    rel_report = case.rel.parent / f"{case.rel.stem}.{case.func.__name__}.txt"
    report = run_dir / rel_report
    report.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    if not verbose:
        term.write(f"{case.id} ... ", end="")

    with report.open("w", encoding="utf-8") as f:
        out = _Out(f, term if verbose else None)
        sep, dash = "=" * _W, "-" * _W
        out.line(sep, "dim")
        out.line(f"{'AMMTEST EXECUTION REPORT':^{_W}}".rstrip(), "bold")
        out.line(sep, "dim")
        out.line(_kv("Test", case.id))
        out.line(_kv("Description", case.meta.description or "(none)"))
        for line in _req_lines(case.meta.requirements):
            out.line(line)
        out.line(_kv("File SHA-256", case.sha256))
        out.line(_kv("Git", _git_text(git)))
        if case.safe_state:
            out.line(_kv("Safe state", _shown(case.safe_state.path)))
            out.line(_kv("Safe state SHA", case.safe_state.sha256))
        else:
            out.line(_kv("Safe state", "(none)"))
        out.line(dash, "dim")
        for line in _ctx_lines(ctx, started):
            out.line(line)
        out.line(sep, "dim")

        log = _Logger(out)
        sut = Sut(client, log, ctx["max_value_age_s"])
        status, error, abort, abort_kind = "PASS", None, None, None
        duration = 0.0

        if case.safe_state:
            out.section("SAFE STATE")
            problem = _apply_safe_state(case.safe_state, client, log, ctx["max_value_age_s"])
            if problem:
                status, error = "ERROR", f"safe state failed, test not run:\n{problem}"
                abort, abort_kind = f"safe state failed before {case.id}: {_last_line(problem)}", "safe_state"

        if not abort:
            try:
                out.section("INITIAL STATE")
                snapshot = sut._snapshot()
                widths = [max(len(row[i]) for row in snapshot) for i in range(4)] if snapshot else [0] * 4
                for row in snapshot:
                    cells = "  ".join(f"{cell:<{w}}" for cell, w in zip(row, widths + [0]))
                    out.line(f"  {cells}".rstrip(), "warn" if row[4].startswith(("STALE", "NEVER")) else "")
                out.section("LOG")
                log.restart()
                t0 = time.monotonic()
                try:
                    case.func(sut)
                finally:
                    duration = time.monotonic() - t0
            except AssertionError as e:
                status, error = "FAIL", _format_exception(e)
            except AmmioConnectionError as e:
                status, error = "ERROR", _format_exception(e)
                abort, abort_kind = f"connection to ammio lost: {e}", "connection"
            except KeyboardInterrupt:
                status, error = "ERROR", "interrupted by user"
                abort, abort_kind = "interrupted by user", "interrupt"
            except Exception as e:
                status, error = "ERROR", _format_exception(e)
            if status == "PASS" and sut.failures:
                status = "FAIL"

        out.section("RESULT")
        out.line(_kv("Status", status), status)
        out.line(_kv("Duration", f"{duration:.3f}s"))
        out.line(_kv("Checks", f"{sut.passed} passed, {len(sut.failures)} failed"))
        _write_failures(out, sut.failures)
        if error:
            out.section("EXCEPTION", "fail")
            for line in error.splitlines():
                out.line(line, "fail")
        out.line(sep, "dim")
        out.line()

    if not verbose:
        term.write(f"{status} ({duration:.3f}s)", status)
        if status != "PASS":
            for fail in sut.failures:
                term.write(f"    {fail.message}", "fail")
                term.write(f"      {fail.file}:{fail.line}  {fail.source}", "dim")
            if error:
                for line in error.splitlines():
                    term.write(f"    {line}", "fail")
    return _Outcome(case, status, started, duration, sut.passed, len(sut.failures), sut.failures,
                    error, rel_report, abort, abort_kind)


def _write_failures(out: _Out, failures: list[Failure]) -> None:
    if not failures:
        return
    out.section("CHECK FAILURES", "fail")
    for i, fail in enumerate(failures, 1):
        out.line(f"  [{i}] {fail.message}", "fail")
        out.line(f"      {fail.file}:{fail.line}  {fail.source}", "fail")


def _final_safe_state(safe_state: SafeState, client: AmmioClient, run_dir: Path, ctx: dict,
                      term: _Term, verbose: bool) -> str:
    """Leave the SUT in safe state at the end of the run; logged to safe_state.txt."""
    if not verbose:
        term.write("safe state (end of run) ... ", end="")
    with (run_dir / "safe_state.txt").open("w", encoding="utf-8") as f:
        out = _Out(f, term if verbose else None)
        sep = "=" * _W
        out.line(sep, "dim")
        out.line(f"{'AMMTEST SAFE STATE (END OF RUN)':^{_W}}".rstrip(), "bold")
        out.line(sep, "dim")
        out.line(_kv("Safe state", _shown(safe_state.path)))
        out.line(_kv("Safe state SHA", safe_state.sha256))
        for line in _ctx_lines(ctx, datetime.now()):
            out.line(line)
        out.line(sep, "dim")
        out.section("LOG")
        problem = _apply_safe_state(safe_state, client, _Logger(out), ctx["max_value_age_s"])
        result = "applied" if problem is None else f"FAILED: {_last_line(problem)}"
        out.section("RESULT")
        out.line(_kv("Status", "APPLIED" if problem is None else "FAILED"), "PASS" if problem is None else "ERROR")
        if problem:
            for line in problem.splitlines():
                out.line(line, "fail")
        out.line(sep, "dim")
    if not verbose:
        term.write("APPLIED" if problem is None else "FAILED", "PASS" if problem is None else "ERROR")
    return result


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


def run(path: str | Path, endpoint: str, results: str | Path = "results", verbose: bool = False,
        max_age: float = DEFAULT_MAX_AGE) -> int:
    """Discover and run every test under `path`. Returns the process exit code."""
    cases = discover(path)
    if not cases:
        raise CollectionError(f"no @ammtest tests found in {path}")

    if not isinstance(max_age, (int, float)) or max_age < 0:
        raise CollectionError(f"max age must be a number of seconds >= 0, got {max_age!r}")
    ctx = _context(endpoint, max_age)
    term = _Term(sys.stdout.isatty() and "NO_COLOR" not in os.environ)
    files = {c.path for c in cases} | {c.safe_state.path for c in cases if c.safe_state}
    git = {f: git_state(f) for f in files}
    started = datetime.now()
    outcomes: list[_Outcome] = []
    aborted, final_safe_state = None, None

    with AmmioClient(endpoint) as client:
        if not client.list_vars():
            raise AmmioError(f"ammio at {endpoint} exposes no variables: is it fully initialized?")
        run_dir = _new_run_dir(Path(results), started)
        for case in cases:
            outcome = _run_one(case, client, run_dir, ctx, git[case.path], term, verbose)
            outcomes.append(outcome)
            if outcome.abort:
                aborted = outcome.abort
                break

        last = outcomes[-1]
        if last.case.safe_state:
            if last.abort_kind in ("connection", "safe_state"):
                final_safe_state = "NOT APPLIED: " + ("connection lost" if last.abort_kind == "connection"
                                                      else "safe state failed")
            else:
                final_safe_state = _final_safe_state(last.case.safe_state, client, run_dir, ctx, term, verbose)

    not_run = [c.id for c in cases[len(outcomes):]]
    uncommitted = sorted(_shown(f) for f, state in git.items() if state is not None and not state["committed"])
    safe_ok = final_safe_state is None or final_safe_state == "applied"
    overall = "ERROR" if aborted or not safe_ok else (
        "PASS" if all(o.status == "PASS" for o in outcomes) else "FAIL")

    summary = {
        **ctx,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "status": overall,
        "aborted": aborted,
        "final_safe_state": final_safe_state,
        "uncommitted_files": uncommitted,
        "totals": _totals(outcomes, not_run),
        "tests": [_test_json(o, run_dir, git[o.case.path]) for o in outcomes],
        "not_run": not_run,
    }
    _write_summary(run_dir, summary)
    _print_summary(term, run_dir, summary)

    if overall == "ERROR":
        return EXIT_ERROR
    return EXIT_PASS if overall == "PASS" else EXIT_FAIL


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


def _test_json(o: _Outcome, run_dir: Path, git: dict | None) -> dict:
    ss = o.case.safe_state
    return {
        "id": o.case.id,
        "status": o.status,
        "description": o.case.meta.description,
        "requirements": o.case.meta.requirements,
        "file_sha256": o.case.sha256,
        "git": git,
        "safe_state": None if ss is None else {"file": _shown(ss.path), "sha256": ss.sha256},
        "started": o.started.isoformat(timespec="milliseconds"),
        "duration_s": round(o.duration, 3),
        "checks_passed": o.checks_passed,
        "checks_failed": o.checks_failed,
        "report": o.report.as_posix(),
        "report_sha256": _sha256_file(run_dir / o.report),
    }


def _write_summary(run_dir: Path, s: dict) -> None:
    (run_dir / "results.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")

    sep, dash = "=" * _W, "-" * _W
    commits = sorted({t["git"]["commit"] for t in s["tests"] if t["git"]})
    lines = [
        sep,
        f"{'AMMTEST RUN SUMMARY':^{_W}}".rstrip(),
        sep,
        _kv("Started", s["started"].replace("T", " ")),
        _kv("Finished", s["finished"].replace("T", " ")),
        _kv("Executed by", s["user"]),
        _kv("Host", s["host"]),
        _kv("Endpoint", s["endpoint"]),
        _kv("Max value age", _max_age_text(s["max_value_age_s"])),
        _kv("Tool", f"ammtest {s['ammtest']}, Python {s['python']}, {s['platform']}"),
        _kv("Git", ", ".join(commits) or "(not under git)"),
        dash,
    ]
    lines += [f"  {t['status']:<7}{t['duration_s']:8.3f}s  {t['id']}" for t in s["tests"]]
    lines += [f"  {'NOT RUN':<7}{'':>9}  {case_id}" for case_id in s["not_run"]]
    lines += [dash, _kv("Status", s["status"])]
    lines += [_kv(k.replace("_", " ").capitalize(), v) for k, v in s["totals"].items()]
    if s["final_safe_state"]:
        lines.append(_kv("Safe state", f"{s['final_safe_state']} (end of run)"))
    if s["aborted"]:
        lines.append(_kv("Aborted", s["aborted"]))
    if s["uncommitted_files"]:
        lines.append(_kv("Uncommitted", s["uncommitted_files"][0]))
        lines += [" " * 18 + f for f in s["uncommitted_files"][1:]]
    lines.append(sep)
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(term: _Term, run_dir: Path, s: dict) -> None:
    t = s["totals"]
    term.write("-" * 60, "dim")
    for case_id in s["not_run"]:
        term.write(f"NOT RUN  {case_id}", "dim")
    text = f"{t['tests']} tests: {t['passed']} passed, {t['failed']} failed, {t['errors']} errors"
    if t["not_run"]:
        text += f", {t['not_run']} not run"
    term.write(text, "PASS" if t["passed"] == t["tests"] else "FAIL")
    if s["final_safe_state"]:
        term.write(f"Safe state (end of run): {s['final_safe_state']}",
                   "dim" if s["final_safe_state"] == "applied" else "ERROR")
    if s["aborted"]:
        term.write(f"Run aborted: {s['aborted']}", "ERROR")
    if s["uncommitted_files"]:
        term.write(f"Warning: uncommitted changes in {', '.join(s['uncommitted_files'])}", "warn")
    term.write(f"Results: {run_dir}", "dim")
