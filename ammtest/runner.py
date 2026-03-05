import importlib.util
import inspect
import logging
import os
import re
import socket
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from .ammio import AmmioClient
from .exceptions import _CheckFailures
from .th import AmmTestHelper

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s"
_LOG_DATE_FORMAT = "%H:%M:%S"
_W = 80  # report width


class _C:
    """ANSI color codes."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    DIM    = "\033[2m"


class _Tee:
    """Writes to terminal (with colors) and file (ANSI stripped) simultaneously."""

    _ANSI = re.compile(r"\033\[[0-9;]*m")

    def __init__(self, file, term):
        self.file = file
        self.term = term

    def write(self, data):
        self.file.write(self._ANSI.sub("", data))
        self.term.write(data)

    def flush(self):
        self.file.flush()
        self.term.flush()


class _ColorFormatter(logging.Formatter):
    """Adds color to WARNING and ERROR log lines in the terminal."""

    _COLORS = {
        logging.WARNING:  _C.YELLOW,
        logging.ERROR:    _C.RED,
        logging.CRITICAL: _C.RED + _C.BOLD,
    }

    def format(self, record):
        msg = super().format(record)
        color = self._COLORS.get(record.levelno, "")
        return f"{color}{msg}{_C.RESET}" if color else msg


def _import_module(file_path: Path):
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discover(base: Path, tests_root: Path) -> list[tuple[Path, callable]]:
    """Return (relative_path, func) for every @ammtest-decorated function under base.
    base can be a single file or a directory.
    rel_path is always relative to tests_root for consistent result folder structure.
    """
    files = [base] if base.is_file() else sorted(
        f for f in base.rglob("*.py") if f.name != "__init__.py"
    )

    tests = []
    for file_path in files:
        module = _import_module(file_path)
        for _, func in inspect.getmembers(module, inspect.isfunction):
            if hasattr(func, "_ammtest_meta"):
                tests.append((file_path.relative_to(tests_root), func))
    return tests


def _row(label: str, value: str) -> str:
    return f"  {label + ':':<16}{value}"


def _ctx_rows(ctx: dict) -> list[str]:
    return [
        _row("Date",        ctx["date"]),
        _row("Time",        ctx["time"]),
        _row("Executed by", ctx["user"]),
        _row("Host",        ctx["host"]),
        _row("Config",      ctx["config_path"]),
    ]


def _write_header(f, rel_path: Path, func_name: str, meta: dict, ctx: dict) -> None:
    sep = _C.DIM + "=" * _W + _C.RESET
    dash = _C.DIM + "-" * _W + _C.RESET
    title = _C.BOLD + f"{'AMMTEST EXECUTION REPORT':^{_W}}" + _C.RESET

    lines = [sep, title, sep] + _ctx_rows(ctx) + [
        dash,
        _row("File",        str(rel_path)),
        _row("Test",        f"{rel_path.stem}::{func_name}"),
    ]

    for key, value in meta.items():
        display = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        lines.append(_row(key.capitalize(), display))

    lines += [sep, "", _C.BOLD + "--- LOG ---" + _C.RESET, ""]

    f.write("\n".join(lines) + "\n")
    f.flush()


def _write_footer(f, status: str, duration: float, error: str | None, failures: list) -> None:
    sep = _C.DIM + "=" * _W + _C.RESET
    color = _C.GREEN if status == "PASS" else _C.RED
    status_display = f"{color}{_C.BOLD}{status}{_C.RESET}"

    lines = [
        "",
        sep,
        _C.BOLD + "--- RESULT ---" + _C.RESET,
        _row("Status",   status_display),
        _row("Duration", f"{duration:.3f}s"),
    ]

    if failures:
        lines += ["", _C.RED + _C.BOLD + "--- CHECK FAILURES ---" + _C.RESET]
        for i, fail in enumerate(failures, 1):
            lines.append(f"  {_C.RED}[{i}] {fail['msg']}{_C.RESET}")
            lines.append(f"  {_C.RED}     {fail['file']}:{fail['lineno']}  {fail['source']}{_C.RESET}")
    if error:
        lines += ["", _C.RED + _C.BOLD + "--- EXCEPTION ---" + _C.RESET, _C.RED + error + _C.RESET]

    lines.append(sep)
    f.write("\n".join(lines) + "\n")
    f.flush()


def _run_one(
    client: AmmioClient,
    rel_path: Path,
    func: callable,
    run_dir: Path,
    ctx: dict,
) -> dict:
    meta = func._ammtest_meta
    func_name = func.__name__

    output_name = f"{rel_path.stem}_{func_name}.txt"
    output_path = run_dir / rel_path.parent / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    status = "PASS"
    error = None

    with open(output_path, "w") as f:
        tee = _Tee(f, sys.stdout)
        _write_header(tee, rel_path, func_name, meta, ctx)

        # log lines go to file (stdout already has stream_handler from run())
        file_handler = logging.StreamHandler(f)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
        root.addHandler(file_handler)

        nparams = len(inspect.signature(func).parameters)
        th = AmmTestHelper(client) if nparams >= 2 else None
        args = (client, th) if th is not None else (client,)

        failures = []
        start = time.monotonic()
        try:
            func(*args)
            if th is not None:
                th.finalize()
        except _CheckFailures as e:
            status = "FAIL"
            failures = e.failures
        except Exception:
            # hard runtime error — preserve full traceback
            status = "FAIL"
            error = traceback.format_exc()
        finally:
            duration = time.monotonic() - start
            root.removeHandler(file_handler)

        _write_footer(tee, status, duration, error, failures)

    return {"rel_path": rel_path, "func_name": func_name, "status": status, "duration": duration}


def _write_summary(run_dir: Path, results: list, ctx: dict, passed: int, failed: int) -> None:
    sep   = "=" * _W
    dash  = "-" * _W
    title = f"{'AMMTEST RUN SUMMARY':^{_W}}"

    lines = [sep, title, sep] + _ctx_rows(ctx) + [dash]

    for r in results:
        label = "PASS" if r["status"] == "PASS" else "FAIL"
        name  = f"{r['rel_path'].with_suffix('')}::{r['func_name']}"
        lines.append(f"  {label:<6}{r['duration']:.3f}s  {name}")

    lines += [
        dash,
        _row("Tests",   str(len(results))),
        _row("Passed",  str(passed)),
        _row("Failed",  str(failed)),
        sep,
    ]

    summary_path = run_dir / "summary.txt"
    summary_path.write_text("\n".join(lines) + "\n")


def run(test_path: str, config: dict, config_path: str = "") -> int:
    """Discover and run all @ammtest tests. Returns 0 if all pass, 1 if any fail."""
    endpoint = config.get("ammio_endpoint")
    results_path = Path(config.get("results_path", "results"))

    now = datetime.now()
    ctx = {
        "date":        now.strftime("%Y-%m-%d"),
        "time":        now.strftime("%H:%M:%S"),
        "user":        os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "host":        socket.gethostname(),
        "config_path": config_path,
    }

    run_dir = results_path / now.strftime("%Y-%m-%d_%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(_ColorFormatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
    root.addHandler(stream_handler)

    base = Path(test_path).resolve()
    tests_root = Path(config.get("tests_path", test_path)).resolve()
    tests = _discover(base, tests_root)

    if not tests:
        print(f"No tests found in {test_path}")
        return 0

    client = AmmioClient(endpoint)

    results = []
    for rel_path, func in tests:
        results.append(_run_one(client, rel_path, func, run_dir, ctx))

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    _write_summary(run_dir, results, ctx, passed, failed)

    root.removeHandler(stream_handler)
    color = _C.GREEN if failed == 0 else _C.RED
    print(f"\n{_C.DIM}{'=' * 60}{_C.RESET}")
    print(f"{len(results)} tests: {color}{_C.BOLD}{passed} passed, {failed} failed{_C.RESET}")
    print(f"{_C.DIM}Results: {run_dir}{_C.RESET}")
    return 0 if failed == 0 else 1