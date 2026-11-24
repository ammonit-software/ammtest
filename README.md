<p align="center">
  <img src="assets/ammtest.png" alt="ammtest" width="350"/>
</p>

<p align="center">
  <strong>Python test framework for critical-software systems. Write, run, and trace system-level tests against any System Under Test (SUT).</strong>
</p>

# ammtest

**ammtest** is a small Python test framework for testing critical-software systems. It talks to the SUT through [ammio](https://github.com/ammonit-software/ammio): it writes inputs, checks outputs over time, and leaves a traceable evidence file for every test.

It addresses three pain points in critical-systems testing:

- *The evidence problem*: certification asks for proof, not "it passed". Every run writes one report per test, plus a machine-readable `results.json`.
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
    version="1.0",
    description="Brake engages within 500 ms of a brake request and holds pressure",
    requirements={"REQ-1416": "A", "REQ-1418": "B"},   # requirement id -> baseline
)
def test_brake_engages(sut):
    sut.write("brake_request", 1)
    sut.check_until("brake_status", 1, timeout=0.5)
    sut.check_stable("brake_pressure", between(80, 120), duration=1.0)
```

```bash
ammtest run tests/                      # ammio at tcp://127.0.0.1:5555
ammtest run tests/ -e tcp://10.0.0.7:5555
```

> Requires [ammio](https://github.com/ammonit-software/ammio) to be running. Set `AMMTEST_ENDPOINT` to change the default endpoint.

Report (`results/<date_time>/TC_001_brake.test_brake_engages.txt`):

```
================================================================================
                            AMMTEST EXECUTION REPORT
================================================================================
  Test:           TC_001_brake.py::test_brake_engages
  Description:    Brake engages within 500 ms of a brake request and holds pressure
  Version:        1.0
  Requirements:   REQ-1416  [A]
                  REQ-1418  [B]
  File SHA-256:   18003b050c825e4772b984e9553295ad2e918c8ccf5866736ec3173e3252dbcf
--------------------------------------------------------------------------------
  Started:        2026-11-24 15:50:34
  Executed by:    jdoe
  Host:           bench-01
  Endpoint:       tcp://127.0.0.1:5555
  Tool:           ammtest 0.2.0, Python 3.13.1, Linux-6.8.0-x86_64-with-glibc2.39
================================================================================

--- LOG ---

15:50:34.750    +0.001s  WRITE  brake_request = 1
15:50:34.964    +0.215s  PASS   brake_status = 1  [== 1]  after 0.213s (timeout 0.5s)
15:50:35.965    +1.216s  PASS   brake_pressure = 100  [in [80, 120]]  held for 1.0s

================================================================================
--- RESULT ---
  Status:         PASS
  Duration:       1.216s
  Checks:         2 passed, 0 failed
================================================================================
```

## Writing tests

A test is a function decorated with `@ammtest` that takes one argument, `sut`.

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
- **Every check returns `True`/`False`**, so a test can branch on it.
- **Timed checks sample every 10 ms** (`interval=` to change it). Measured times have that resolution plus one ammio round trip.

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

### Status

| Status | When |
|--------|------|
| `PASS` | No check failed |
| `FAIL` | A check failed, or a plain `assert` failed |
| `ERROR` | The test could not execute: unknown variable, bug in the test, ... |

If the connection to ammio is lost (or you press Ctrl+C), the run stops. The remaining tests are reported as `NOT RUN`.

### Organising tests

- `ammtest run` takes a file or a folder. Folders are searched recursively. Files run in sorted order, and tests within a file run in definition order.
- Files and folders starting with `.` or `_` are skipped, so put shared code in `_helpers.py` and `from _helpers import ...` it.
- If any file fails to import, or a test has the wrong signature, nothing runs (exit code 2).

## Command line

```bash
ammtest run <path> [-e ENDPOINT] [-r RESULTS]   # run tests, write evidence
ammtest vars [-e ENDPOINT]                       # list the variables ammio exposes
ammtest trace <path>                             # tests -> requirements
ammtest trace <path> --reqs reqs.csv [--col N] [--delimiter ";"] [--skip-header]
```

`trace` does not connect to ammio:

- **Without `--reqs`**, it lists each test with its requirements and fails if a test has none.
- **With `--reqs`**, it lists each requirement in the file (CSV, or one id per line) with the tests covering it. It fails if a requirement is not covered, or if a test references an id that isn't in the file (typos, withdrawn requirements).

| Exit code | Meaning |
|-----------|---------|
| `0` | All tests passed / traceability complete |
| `1` | A test failed or errored / traceability gap |
| `2` | Could not run: bad usage, import error, no tests, ammio unreachable or lost |

## Results

```
results/2026-11-24_15-50-34/
  TC_001_brake.test_brake_engages.txt     one evidence report per test (folder structure mirrors the tests)
  summary.txt                             human-readable run summary
  results.json                            machine-readable: statuses, requirements, file hashes, timings
```

Every report records the SHA-256 of the exact test file that ran, the ammtest and Python versions, the platform, the user, the host and the endpoint.

## Design for qualification

- **Small and reviewable.** Under 1,000 lines including docstrings, a single runtime dependency (`pynng`), and no plugins or hidden configuration.
- **Deterministic evidence.** Report text comes from explicit condition objects, never from parsing source code.
- **Verified.** The framework has its own test suite (`uv run pytest`), run against an in-process fake ammio on Linux and Windows, with Python 3.12 and 3.13.

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
