"""Sut: the single object every test receives. Drive inputs, check outputs."""

import linecache
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .client import AmmioClient, Value
from .conditions import as_condition

POLL_INTERVAL = 0.01  # seconds between samples in timed checks
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

Log = Callable[..., None]


@dataclass(frozen=True)
class Failure:
    message: str
    file: str
    line: int
    source: str


def _print_log(text: str, style: str = "") -> None:
    print(text)


def _nonneg(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a number >= 0, got {value!r}")


class Sut:
    """Handle on the System Under Test, passed to every test function.

    - Every call is logged with a timestamp in the test report.
    - Checks are soft: a failed check is recorded and the test goes on;
      the test FAILs at the end if any check failed.
    - Every check returns True/False, so a test can branch on it.
    - `expected` is a value (equality), a Condition (eq, between, approx, ...)
      or any callable.
    - Timed checks sample every `interval` seconds; measured times have that
      resolution plus one ammio round trip.
    """

    def __init__(self, client: AmmioClient, log: Log = _print_log):
        self._client = client
        self._log = log
        self.failures: list[Failure] = []
        self.passed = 0

    # --- I/O -------------------------------------------------------------

    def write(self, var_id: str, value: Value) -> None:
        """Force SUT input `var_id` to `value`."""
        self._client.write(var_id, value)
        self._log(f"WRITE  {var_id} = {value!r}")

    def read(self, var_id: str) -> Value:
        """Read `var_id` and log it (no verdict)."""
        value = self._client.read(var_id)
        self._log(f"READ   {var_id} = {value!r}")
        return value

    def wait(self, seconds: float) -> None:
        """Sleep for `seconds`."""
        _nonneg("seconds", seconds)
        self._log(f"WAIT   {seconds}s")
        time.sleep(seconds)

    def log(self, message: str) -> None:
        """Add a note to the report (test step, rationale, ...)."""
        self._log(f"NOTE   {message}")

    # --- checks ----------------------------------------------------------

    def check(self, var_id: str, expected: Any) -> bool:
        """`var_id` satisfies `expected` right now."""
        cond = as_condition(expected)
        value = self._client.read(var_id)
        return self._verdict("check", cond(value), f"{var_id} = {value!r}  [{cond}]")

    def check_until(self, var_id: str, expected: Any, timeout: float, interval: float = POLL_INTERVAL) -> bool:
        """`var_id` satisfies `expected` at some point within `timeout` seconds."""
        _nonneg("timeout", timeout)
        cond = as_condition(expected)
        start = time.monotonic()
        while True:
            value = self._client.read(var_id)
            elapsed = time.monotonic() - start
            ok = cond(value)
            if ok and elapsed <= timeout:
                return self._verdict(
                    "check_until", True,
                    f"{var_id} = {value!r}  [{cond}]  after {elapsed:.3f}s (timeout {timeout}s)",
                )
            if elapsed >= timeout:
                return self._verdict(
                    "check_until", False,
                    f"{var_id} = {value!r}  [{cond}]  not reached within {timeout}s",
                )
            time.sleep(min(interval, timeout - elapsed))

    def check_stable(self, var_id: str, expected: Any, duration: float, interval: float = POLL_INTERVAL) -> bool:
        """`var_id` satisfies `expected` continuously for `duration` seconds."""
        _nonneg("duration", duration)
        cond = as_condition(expected)
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start  # taken before the read: last sample is at/after `duration`
            value = self._client.read(var_id)
            if not cond(value):
                return self._verdict(
                    "check_stable", False,
                    f"{var_id} = {value!r}  [{cond}]  broke after {elapsed:.3f}s (required {duration}s)",
                )
            if elapsed >= duration:
                return self._verdict(
                    "check_stable", True,
                    f"{var_id} = {value!r}  [{cond}]  held for {duration}s",
                )
            time.sleep(min(interval, duration - elapsed))

    def check_at(
        self, var_id: str, expected: Any, at: float, tolerance: float = 0.1, interval: float = POLL_INTERVAL
    ) -> bool:
        """`var_id` starts satisfying `expected` at `at` +- `tolerance` seconds from now.

        Already satisfied at the first sample counts as a transition at ~0s.
        """
        _nonneg("at", at)
        _nonneg("tolerance", tolerance)
        cond = as_condition(expected)
        window = f"expected {at}s +- {tolerance}s"
        start = time.monotonic()
        while True:
            value = self._client.read(var_id)
            elapsed = time.monotonic() - start
            if cond(value):
                if elapsed < at - tolerance:
                    return self._verdict(
                        "check_at", False,
                        f"{var_id} = {value!r}  [{cond}]  too early: {elapsed:.3f}s ({window})",
                    )
                if elapsed <= at + tolerance:
                    return self._verdict(
                        "check_at", True,
                        f"{var_id} = {value!r}  [{cond}]  at {elapsed:.3f}s ({window})",
                    )
            if elapsed >= at + tolerance:
                return self._verdict(
                    "check_at", False,
                    f"{var_id} = {value!r}  [{cond}]  no transition by {at + tolerance:.3f}s ({window})",
                )
            time.sleep(min(interval, at + tolerance - elapsed))

    # --- internals -------------------------------------------------------

    def _verdict(self, kind: str, ok: bool, detail: str) -> bool:
        if ok:
            self.passed += 1
            self._log(f"PASS   {detail}", "pass")
        else:
            self._log(f"FAIL   {detail}", "fail")
            self.failures.append(Failure(f"{kind}: {detail}", *_caller()))
        return ok


def _caller() -> tuple[str, int, str]:
    """Location of the first frame outside ammtest: the line that called the check."""
    frame = sys._getframe(1)
    while frame is not None and os.path.dirname(os.path.abspath(frame.f_code.co_filename)) == _PKG_DIR:
        frame = frame.f_back
    if frame is None:
        return "?", 0, ""
    filename, line = frame.f_code.co_filename, frame.f_lineno
    try:
        shown = os.path.relpath(filename)
    except ValueError:  # other drive on Windows
        shown = filename
    return shown, line, linecache.getline(filename, line).strip()
