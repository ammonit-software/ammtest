<p align="center">
  <img src="assets/ammtest.png" alt="ammtest" width="350"/>
</p>

<p align="center">
  <strong>Python test framework for critical-software systems. Write, run, and trace system-level tests against any System Under Test (SUT).</strong>
</p>

# ammtest

**ammtest** is a Python test framework for testing critical-software systems. It connects to [ammio](https://github.com/ammonit-software/ammio) to interact with the SUT — writing inputs, reading outputs, and asserting behavior — with full traceability built in.

It addresses three core pain points in critical systems testing:

- *The evidence problem*: Tests run, tests pass — but certification asks for proof. **ammtest** writes a structured, traceable result file on every execution, automatically. The test itself becomes the specification.
- *The traceability gap*: Requirements live in one document, tests live in another, and nobody can prove they match. **ammtest** binds them at the source — no spreadsheets, no manual cross-referencing.
- *The infrastructure tax*: Connecting to a real system takes more code than the test itself. **ammtest** handles the communication layer, so you write stimulus and assertions — nothing else.

## Quickstart

### Install

```bash
uv pip install ammtest
```

### Write a test

```python
from ammtest import ammtest, AmmioClient, AmmTestHelper

@ammtest(
    version="0.1.0",
    description="Check if brake engages on request",
    requirements=[
        {"req": "REQ-1416", "baseline": "A"},
        {"req": "REQ-1418", "baseline": "B"},
    ],
)
def test(cl: AmmioClient, th: AmmTestHelper):
    # Force SUT input via ammio
    cl.write("brake_request", 1) 
    
    # Wait for the SUT to react (0.5s)
    th.wait(0.5)
    
    # Check status and log results (traced to REQ-1416/1418)
    th.check("brake_status", lambda v: v == 1)
```

### Run

```bash
ammtest run tests/TC_001.py --endpoint=tcp://127.0.0.1:5555
```

> Note: requires [ammio](https://github.com/ammonit-software/ammio) to be running.

### Log

```
================================================================================
                            AMMTEST EXECUTION REPORT
================================================================================
  Date:           2026-03-06
  Time:           16:43:36
  Executed by:    jdoe
  Host:           my-machine
--------------------------------------------------------------------------------
  File:           TC_001.py
  Test:           TC_001::test
  Version:        0.1.0
  Description:    Check if brake engages on request
  Requirements:   req: REQ-1416            baseline: [A]
                  req: REQ-1418            baseline: [B]
================================================================================

--- LOG ---

16:43:36.531 INFO     WRITE: brake_request = 1
16:43:37.033 INFO     CHECK PASS  brake_status = 1  [v == 1]

================================================================================
--- RESULT ---
  Status:         PASS
  Duration:       0.502s
================================================================================
```

## Architecture

**ammtest** discovers `@ammtest`-decorated functions, runs each against a live ammio instance, and writes result files to disk. No test framework overhead — plain Python functions, plain files.

```
  test functions (@ammtest decorator)
         │
         │  cl.write("var", value)                    →  write SUT inputs
         │  th.check("var", lambda v: v == 1)         ←  one-shot check, reading SUT outputs
         │
  ┌──────┴───────────────────────────────────────────────────────┐
  │                          ammtest                             │
  │  ┌──────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
  │  │ @ammtest │  │ AmmioClient │  │    AmmTestHelper        │  │
  │  │ metadata │  │ nng REQ/REP │  │  check / check_stable   │  │
  │  └──────────┘  └──────┬──────┘  │  check_until / check_at │  │
  │                       │         └─────────────────────────┘  │
  │                   runner: discover, run, write results       │
  └───────────────────────│──────────────────────────────────────┘
                          │ nng REQ/REP · JSON · TCP
                          ▼
                         ammio → SUT
```

**`@ammtest` decorator**: Tags a function as a test case. Attaches `version`, `description`, and `requirements` as metadata directly on the function.

**`AmmioClient` (`cl`)**: Connects to ammio over nng REQ/REP. `write(var_id, value)` forces SUT inputs; `read(var_id)` observes SUT outputs. Errors from ammio are resolved to human-readable names and raised as `AmmioError`.

**`AmmTestHelper` (`th`)**: Injected as the second argument to each test function. Provides check methods and a wait helper — each check reads a variable, evaluates a lambda condition, and emits a `CHECK PASS` / `CHECK FAIL` log line with the variable name, actual value, and condition expression.

| Method | Semantics |
|--------|-----------|
| `th.check(var, cond)` | Value satisfies condition **right now** |
| `th.check_stable(var, cond, duration)` | Condition holds for entire `duration` seconds |
| `th.check_until(var, cond, timeout)` | Condition becomes true **within** `timeout` seconds |
| `th.check_at(var, cond, at, tolerance)` | Condition first becomes true at `at` +- `tolerance` seconds |
| `th.wait(duration)` | Sleep for `duration` seconds, logging start and end |

**Runner**: Discovers all `@ammtest` functions under a path, runs each in sequence, writes one `.txt` result file per test. Result files include a full execution header (date, user, host, metadata), real-time log output, status, duration, and error details.

**Traceability commands**: Two static analysis commands operate on test files without connecting to ammio.

| Command | Output |
|---------|--------|
| `ammtest trace-tests <path>` | One row per test — which requirements it covers. Flags tests with no requirements. |
| `ammtest trace-reqs <path> --reqs=<csv> --col=<n>` | One row per requirement from the CSV — which tests cover it. Flags requirements with no test. |

`trace-reqs` options:
- `--col=<n>` — 1-based column number where requirement IDs are
- `--skip-header` — skip the first row if the CSV has a header
- `--delimiter="<char>"` — column separator (default: `,`); quote special characters to avoid shell interpretation

```bash
ammtest trace-tests tests/
ammtest trace-reqs tests/ --reqs=requirements.csv --col=1 --skip-header
ammtest trace-reqs tests/ --reqs=requirements.csv --col=2 --skip-header --delimiter=";"
```

## Related Projects

- **[ammio](https://github.com/ammonit-software/ammio)**: Protocol agnostic test interface for critical-software systems. Talk to any System Under Test (SUT) in JSON, regardless of its protocol.
- **[Ammonit Software](https://github.com/ammonit-software)**: Parent organization.

## License

This project is open source and available under the [MIT License](LICENSE).

