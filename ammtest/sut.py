"""Sut: the single object every test receives. Drive inputs, check outputs."""

import difflib
import linecache
import math
import os
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .client import AmmioClient, AmmioError, StaleValueError, Value
from .conditions import as_condition

POLL_INTERVAL = 0.01  # seconds between samples in timed checks
DEFAULT_MAX_AGE = 1.0  # seconds; older SUT outputs are stale (ammio interfaces refresh every 100 ms by default)
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# ammio stores a written value with a plain C cast: out-of-range integers wrap
# and decimals are truncated without any error. Refuse those writes instead.
INT_RANGES = {
    "uint8": (0, 2**8 - 1),
    "int8": (-(2**7), 2**7 - 1),
    "uint16": (0, 2**16 - 1),
    "int16": (-(2**15), 2**15 - 1),
    "uint32": (0, 2**32 - 1),
    "int32": (-(2**31), 2**31 - 1),
}


def stored_value(var_id: str, vtype: str | None, value: Value) -> Value:
    """The value ammio will actually hold after writing `value` to a `vtype` variable.

    Raises ValueError for writes ammio would silently corrupt.
    """
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"cannot write {value!r} to {var_id!r}: a finite number is required")
    if vtype in INT_RANGES:
        low, high = INT_RANGES[vtype]
        if value != int(value):
            raise ValueError(f"cannot write {value!r} to {var_id!r}: {vtype} only holds whole numbers")
        if not low <= value <= high:
            raise ValueError(f"cannot write {value!r} to {var_id!r}: {vtype} range is [{low}, {high}]")
        return int(value)
    if vtype == "float32":
        try:
            return struct.unpack("<f", struct.pack("<f", value))[0]
        except OverflowError:
            raise ValueError(f"cannot write {value!r} to {var_id!r}: out of float32 range") from None
    return value

Log = Callable[..., None]


@dataclass(frozen=True)
class Failure:
    message: str
    file: str
    line: int
    source: str


def value_age(stamp: int | None) -> float | None:
    """Seconds since ammio last updated a value (ammio's clock vs this computer's clock)."""
    return None if not stamp else time.time() - stamp / 1e9


def check_fresh(var_id: str, stamp: int | None, max_age: float) -> None:
    """Raise StaleValueError unless ammio updated `var_id` within the last `max_age` seconds."""
    if stamp is None:
        raise StaleValueError(f"ammio reported no timestamp for {var_id!r}; freshness cannot be verified")
    if stamp == 0:
        raise StaleValueError(f"{var_id!r} has never been received from the SUT")
    age = value_age(stamp)
    if age > max_age:
        raise StaleValueError(f"{var_id!r} is stale: last received from the SUT {age:.3f}s ago (max age {max_age}s)")
    if age < -max_age:
        raise StaleValueError(
            f"{var_id!r} has a timestamp {-age:.3f}s in the future: "
            "ammio's clock and this computer's clock are not synchronized"
        )


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
    - Every read of a SUT output is checked for freshness: if ammio has not
      received it from the SUT within `max_age` seconds, the read raises
      StaleValueError (the test is an ERROR). `max_age=0` disables the check.
    """

    def __init__(self, client: AmmioClient, log: Log = _print_log, max_age: float = DEFAULT_MAX_AGE):
        _nonneg("max_age", max_age)
        self._client = client
        self._log = log
        self.max_age = max_age
        self._vars: dict[str, dict] = {}  # ammio's variable table, fetched on first use
        self.failures: list[Failure] = []
        self.passed = 0

    # --- I/O -------------------------------------------------------------

    def write(self, var_id: str, value: Value) -> None:
        """Force SUT input `var_id` to `value`.

        Refused (ERROR) if `var_id` is a SUT output, or if the variable's type
        cannot hold `value` exactly (ammio would wrap or truncate it silently).
        """
        info = self._var(var_id)
        if info.get("dir") == "output":
            raise AmmioError(f"cannot write {var_id!r}: it is a SUT output (read-only)")
        stored = stored_value(var_id, info.get("type"), value)
        self._client.write(var_id, value)
        note = "" if repr(stored) == repr(value) else f"  (stored as {info.get('type')} {stored!r})"
        self._log(f"WRITE  {var_id} = {value!r}{note}")

    def read(self, var_id: str) -> Value:
        """Read `var_id` and log it (no verdict)."""
        value = self._read(var_id)
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
        self._var(var_id)
        cond = as_condition(expected)
        value = self._read(var_id)
        return self._verdict("check", cond(value), f"{var_id} = {value!r}  [{cond}]")

    def check_until(self, var_id: str, expected: Any, timeout: float, interval: float = POLL_INTERVAL) -> bool:
        """`var_id` satisfies `expected` at some point within `timeout` seconds."""
        _nonneg("timeout", timeout)
        self._var(var_id)
        cond = as_condition(expected)
        start = time.monotonic()
        while True:
            value = self._read(var_id)
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
        self._var(var_id)
        cond = as_condition(expected)
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start  # taken before the read: last sample is at/after `duration`
            value = self._read(var_id)
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
        self._var(var_id)
        cond = as_condition(expected)
        window = f"expected {at}s +- {tolerance}s"
        start = time.monotonic()
        while True:
            value = self._read(var_id)
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

    def _var(self, var_id: str) -> dict:
        """ammio's description of `var_id`; unknown names fail with a suggestion."""
        info = self._vars.get(var_id)
        if info is None:  # first use, or the table changed: refresh once
            self._vars = {v["var_id"]: v for v in self._client.list_vars()}
            info = self._vars.get(var_id)
        if info is None:
            close = difflib.get_close_matches(str(var_id), list(self._vars), n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            raise AmmioError(f"unknown variable {var_id!r}{hint}")
        return info

    def _read(self, var_id: str) -> Value:
        info = self._var(var_id)
        value, stamp = self._client.read_sample(var_id)
        if self.max_age and info.get("dir") == "output":
            check_fresh(var_id, stamp, self.max_age)
        return value

    def _snapshot(self) -> list[tuple[str, str, str, str, str]]:
        """(var_id, type, dir, value, freshness) for every variable, sorted by name.

        Never raises for stale values: unused stale outputs must not fail a test.
        Reads are sequential, not one atomic snapshot.
        """
        self._vars = {v["var_id"]: v for v in self._client.list_vars()}
        rows = []
        for var_id, info in sorted(self._vars.items()):
            value, stamp = self._client.read_sample(var_id)
            freshness = ""
            if info.get("dir") == "output":
                age = value_age(stamp)
                if stamp is None:
                    freshness = "no timestamp"
                elif age is None:
                    freshness = "NEVER RECEIVED"
                elif self.max_age and abs(age) > self.max_age:
                    freshness = f"STALE (age {age:.3f}s)"
                else:
                    freshness = f"age {age:.3f}s"
            rows.append((var_id, str(info.get("type", "")), str(info.get("dir", "")), repr(value), freshness))
        return rows

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
