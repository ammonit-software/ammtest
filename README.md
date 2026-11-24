<p align="center">
  <img src="assets/ammtest.png" alt="ammtest" width="350"/>
</p>

<p align="center">
  <strong>Python test framework for critical-software systems. Write, run, and trace system-level tests against any System Under Test (SUT).</strong>
</p>

# ammtest

**ammtest** is a small Python test framework for testing critical-software systems. It talks to the SUT through [ammio](https://github.com/ammonit-software/ammio): it writes inputs, checks outputs over time, and leaves a traceable evidence file for every test.

It addresses three pain points in critical-systems testing:

- *The evidence problem*: certification asks for proof, not "it passed". Every run writes one report per test, plus a machine-readable `results.json`. Each report records the exact test file (SHA-256 and git commit), the SUT state before the test, and every stimulus and check.
- *The traceability gap*: requirements and tests drift apart. Here each test declares its requirements, and `ammtest trace` checks them against your requirements file.
- *The infrastructure tax*: you write stimulus and checks, nothing else.

It is deliberately minimal, to keep it easy to learn, review and qualify. The only runtime dependency is `pynng`.

## Quickstart

```bash
uv pip install ammtest
```

```python
# tests/TC_001_brake.py
from ammtest import ammtest, between

@ammtest(
    description="Brake engages within 500 ms of a brake request and holds pressure",
    requirements={"REQ-1416": "A", "REQ-1418": "B"},   # requirement id -> baseline
)
def test_brake_engages(sut):
    sut.write("brake_request", 1)
    sut.check_until("brake_status", 1, timeout=0.5)
    sut.check_stable("brake_pressure", between(80, 120), duration=1.0)
```

```bash
ammtest run tests/                                  # ammio at tcp://127.0.0.1:5555
ammtest run tests/ -e tcp://10.0.0.7:5555
ammtest run tests/TC_001_brake.py::test_brake_engages -v   # one test, full log on screen
```

> Requires [ammio](https://github.com/ammonit-software/ammio) to be running. Set `AMMTEST_ENDPOINT` to change the default endpoint.

The terminal shows one line per test (plus the reason when one fails); `-v` streams the full report instead:

```
TC_001_brake.py::test_brake_engages ... PASS (1.221s)
safe state (end of run) ... APPLIED
------------------------------------------------------------
1 tests: 1 passed, 0 failed, 0 errors
Safe state (end of run): applied
Results: results/2026-11-24_16-03-48
```

The evidence report (`results/<date_time>/TC_001_brake.test_brake_engages.txt`):

```
================================================================================
                            AMMTEST EXECUTION REPORT
================================================================================
  Test:           TC_001_brake.py::test_brake_engages
  Description:    Brake engages within 500 ms of a brake request and holds pressure
  Requirements:   REQ-1416  [A]
                  REQ-1418  [B]
  File SHA-256:   1422b9fa516a29beb3b548191aae5879a563dc08c2dc8aa5240fcbce3b2ffb69
  Git:            eeecdf97c1dde4818c9c345fe386f56481933a8b  (committed)
  Safe state:     _safe_state.py
  Safe state SHA: 9f272d00e48bfa87b754c0da0772fe386669109f2bc30df42182225cea0f43c4
--------------------------------------------------------------------------------
  Started:        2026-11-24 16:03:48
  Executed by:    jdoe
  Host:           bench-01
  Endpoint:       tcp://127.0.0.1:5555
  Max value age:  1.0s (older SUT outputs are an ERROR)
  Tool:           ammtest 0.2.0, Python 3.13.1, Linux-6.8.0-x86_64-with-glibc2.39
================================================================================

--- SAFE STATE ---

16:03:48.887    +0.001s  WRITE  brake_request = 0
16:03:49.098    +0.212s  PASS   brake_status = 0  [== 0]  after 0.211s (timeout 1.0s)

--- INITIAL STATE ---

  brake_pressure  float32  output  0.0  age 0.042s
  brake_request   uint8    input   0
  brake_status    uint8    output  0    age 0.042s

--- LOG ---

16:03:49.112    +0.000s  WRITE  brake_request = 1
16:03:49.319    +0.207s  PASS   brake_status = 1  [== 1]  after 0.207s (timeout 0.5s)
16:03:50.321    +1.209s  PASS   brake_pressure = 100.0  [in [80, 120]]  held for 1.0s

--- RESULT ---

  Status:         PASS
  Duration:       1.209s
  Checks:         2 passed, 0 failed
================================================================================
```

## Writing tests

A test is a function decorated with `@ammtest` that takes one argument, `sut`. Its identity in the evidence is its file's SHA-256 and git commit, so there is no version field to maintain.

### `sut`: inputs and checks

| Call | Meaning |
|------|---------|
| `sut.write(var, value)` | Force a SUT input |
| `sut.read(var)` | Read and log a value (no verdict) |
| `sut.check(var, expected)` | Satisfied **right now** |
| `sut.check_until(var, expected, timeout)` | Becomes satisfied **within** `timeout` s |
| `sut.check_stable(var, expected, duration)` | Stays satisfied for the **whole** `duration` s |
| `sut.check_at(var, expected, at, tolerance=0.1)` | **Starts** being satisfied at `at` ± `tolerance` s |
| `sut.wait(seconds)` | Sleep |
| `sut.log(message)` | Add a note to the report (test step, rationale) |

- **Checks are soft.** A failed check is logged and recorded, and the test goes on. The test FAILs at the end if any check failed, and the report lists each failure with `file:line`.
- **Every check returns `True`/`False`.** To stop the test when a precondition fails, write `assert sut.check_until(...)`.
- **Timed checks sample every 10 ms** (`interval=` to change it). Measured times have that resolution plus one ammio round trip. They can never be finer than the bus cycle of ammio's interface (`period_ms`, 100 ms by default).

### Variables are checked against ammio's variable table

A value that ammio would silently corrupt is never written. These cases fail the test as ERROR before anything is sent:

- **Unknown names:** `unknown variable 'brake_stauts' (did you mean 'brake_status'?)`
- **Writing a SUT output:** outputs are read-only.
- **Values the type can't hold.** ammio stores values with a plain C cast, so without this check:
  - `300` written to a `uint8` would be stored as `44`;
  - `1.7` written to an `int16` would be stored as `1`.

When the stored value differs from the written one, the log shows both:

```
WRITE  door_closed = True  (stored as uint8 1)
WRITE  ref_voltage = 0.1  (stored as float32 0.10000000149011612)
```

Compare `float32` values with `approx`, not equality.

### `expected`: values and conditions

```python
from ammtest import eq, ne, lt, le, gt, ge, between, approx, Condition

sut.check("brake_status", 1)                     # plain value = equality   -> [== 1]
sut.check("speed", lt(5))                        #                          -> [< 5]
sut.check("voltage", approx(3.3, tol=0.1))       #                          -> [== 3.3 +- 0.1]
sut.check("pressure", between(80, 120))          # bounds included          -> [in [80, 120]]
sut.check("mode", Condition(lambda v: v in (2, 3), "is 2 or 3"))   # custom -> [is 2 or 3]
```

Each condition describes itself in the report, so the evidence reads the same whichever way the test was written.

### Stale values are an ERROR, not a PASS

ammio keeps the last value it received for each output. If the bus or the SUT goes silent, `read` keeps returning that last value, and a test could pass against data that is minutes old.

Every reply from ammio carries the time the value was last received from the SUT, and ammtest checks it on every read of an output:

```
StaleValueError: 'brake_status' is stale: last received from the SUT 5.006s ago (max age 1.0s)
```

- **Default limit:** 1 s, which is 10 bus cycles of ammio's default 100 ms `period_ms`.
- **Changing it:** `--max-age SECONDS` or `AMMTEST_MAX_AGE`; `--max-age 0` disables the check. The value used is recorded in every report.
- **In the INITIAL STATE table** each output shows its age. A stale output there is flagged but doesn't fail the test unless the test reads it.
- **Inputs are never checked:** an input that was last written a minute ago is normal.
- **Clocks:** if ammio runs on another machine, both clocks must be synchronised (NTP). A timestamp more than `max_age` in the future is reported as an ERROR, because it means the clocks have drifted.

### Safe state

Put a `_safe_state.py` next to your tests:

```python
def safe_state(sut):
    sut.write("brake_request", 0)
    sut.check_until("brake_status", 0, timeout=1.0)
```

- **When it runs:** before every test, and at the end of the run. That includes a run stopped by a test error or by Ctrl+C.
- **What it gives you:** every test starts from a known state, and the rig is never left half-way through a test.
- **Which file is used:** the nearest `_safe_state.py` in the test's folder or any parent folder. Different subfolders can have different ones.
- **Where it's logged:** the safe state applied before a test is in that test's report, followed by a snapshot of every variable (INITIAL STATE). The one applied at the end of the run is in `safe_state.txt`.
- **If it fails** (an exception or a failed check), the run stops at once and the remaining tests are NOT RUN. The rig may not be safe.

### Status

| Status | When |
|--------|------|
| `PASS` | No check failed |
| `FAIL` | A check failed, or a plain `assert` failed |
| `ERROR` | The test could not execute: unknown variable, refused write, stale SUT output, bug in the test, safe state failed |

If the connection to ammio is lost, a safe state fails, or you press Ctrl+C, the run stops. The remaining tests are reported as `NOT RUN`.

### Organising tests

- `ammtest run` takes a file, a folder (searched recursively), or `file::test_name`. Files run in sorted order, and tests within a file run in definition order.
- Files and folders starting with `.` or `_` are skipped, so put shared code in `_helpers.py` and `from _helpers import ...` it.
- If any file fails to import, or a test has the wrong signature, nothing runs (exit code 2).

## Command line

```bash
ammtest run <path> [-e ENDPOINT] [-r RESULTS] [-v] [--max-age SECONDS]   # run tests, write evidence
ammtest vars [-e ENDPOINT]                            # list the variables ammio exposes
ammtest trace <path>                                  # tests -> requirements
ammtest trace <path> --reqs reqs.csv [--col N] [--delimiter ";"] [--skip-header]
```

`trace` does not connect to ammio:

- **Without `--reqs`**, it lists each test with its requirements and fails if a test has none.
- **With `--reqs`**, it lists each requirement in the file (CSV, or one id per line) with the tests covering it. It fails if a requirement is not covered, or if a test references an id that isn't in the file (typos, withdrawn requirements).

| Exit code | Meaning |
|-----------|---------|
| `0` | All tests passed / traceability complete |
| `1` | A test failed or errored / traceability gap |
| `2` | Could not run or complete: bad usage, import error, no tests, ammio unreachable or lost, safe state failed, Ctrl+C |

## Results

```
results/2026-11-24_16-03-48/
  TC_001_brake.test_brake_engages.txt   one evidence report per test (folder structure mirrors the tests)
  safe_state.txt                        safe state applied at the end of the run
  summary.txt                           human-readable run summary
  results.json                          machine-readable: statuses, requirements, hashes, git state, timings
```

Configuration management of the evidence:

- **Exact code identified:** each report records the SHA-256 of the test file and of the safe-state file, plus the git commit.
- **Uncommitted changes flagged:** an executed file that is modified or untracked is marked `(UNCOMMITTED CHANGES)`. The run also ends with a warning, so an informal run can't pass as formal evidence.
- **Reports can't be edited unnoticed:** `results.json` holds the SHA-256 of every report.

## Design for qualification

- **Small and reviewable.** About 1,300 lines including docstrings, a single runtime dependency (`pynng`), and no plugins or hidden configuration.
- **Deterministic evidence.** Report text comes from explicit condition objects, never from parsing source code. Values are logged as ammio actually stores them.
- **Verified.** The framework has its own test suite (`uv run pytest`), run against an in-process fake ammio that mirrors ammio's protocol (error codes, directions, C-cast storage). CI runs it on Linux and Windows, with Python 3.12 and 3.13.

## Migrating from 0.1

| 0.1 | 0.2 |
|-----|-----|
| `def test(cl: AmmioClient, th: AmmTestHelper)` | `def test(sut)` |
| `cl.write("x", 1)` / `cl.read("x")` | `sut.write("x", 1)` / `sut.read("x")` |
| `th.check("x", lambda v: v == 1)` | `sut.check("x", 1)` |
| `th.check("x", lambda v: 80 <= v <= 120)` | `sut.check("x", between(80, 120))` |
| `th.check_until / check_stable / check_at / wait` | same names on `sut` |
| `requirements=[{"req": "REQ-1", "baseline": "A"}]` | `requirements={"REQ-1": "A"}` |
| `version="0.1.0"` | removed: the file hash and git commit identify the test |
| `ammtest trace-tests <path>` | `ammtest trace <path>` |
| `ammtest trace-reqs <path> --reqs=f.csv --col=1` | `ammtest trace <path> --reqs f.csv --col 1` |
| `--tests-root`, `--output` | removed (redirect output with `>` if needed) |
| exit code always 0 | 0 pass, 1 failed, 2 could not run |

## Development

```bash
uv sync
uv run pytest
```

## Related Projects

- **[ammio](https://github.com/ammonit-software/ammio)**: Protocol agnostic test interface for critical-software systems. Talk to any System Under Test (SUT) in JSON, regardless of its protocol.
- **[Ammonit Software](https://github.com/ammonit-software)**: Parent organization.

## License

This project is open source and available under the [MIT License](LICENSE).
