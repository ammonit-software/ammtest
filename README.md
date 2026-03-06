<p align="center">
  <img src="assets/ammtest.png" alt="ammtest" width="350"/>
</p>

<p align="center">
  <strong>Python test framework for critical-software systems. Write, run, and trace system-level tests against any System Under Test (SUT).</strong>
</p>

# ammtest

**ammtest** is a Python test framework for testing critical-software systems. It connects to [ammio](https://github.com/ammonit-software/ammio) to interact with the SUT — writing inputs, reading outputs, and asserting behavior — with full traceability built in.

Every test is tagged with metadata (version, description, requirements) and produces a structured `.txt` result file per execution, ready for review or certification evidence.

## Quickstart

### Install

```bash
pip install ammtest
```

### Write a test

```python
import time
from ammtest import ammtest, AmmioClient, AmmTestHelper

@ammtest(version="0.1.0", description="Brake engages on request", requirements=["REQ-042"])
def test(cl: AmmioClient, th: AmmTestHelper):
    cl.write("brake_request", 1)  # force SUT input via ammio
    time.sleep(0.5)               # wait for the SUT to react
    th.check("brake_status", lambda v: v == 1)  # CHECK PASS/FAIL logged, traced to REQ-042
```

### Run

```bash
ammtest run tests/TC_001.py --ammtest-config=config/config.json
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
  Config:         config/config.json
--------------------------------------------------------------------------------
  File:           TC_001.py
  Test:           TC_001::test
  Version:        0.1.0
  Description:    Brake engages on request
  Requirements:   REQ-042
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

**`AmmTestHelper` (`th`)**: Injected as the second argument to each test function. Provides four check methods — each reads a variable, evaluates a lambda condition, and emits a `CHECK PASS` / `CHECK FAIL` log line with the variable name, actual value, and condition expression.

| Method | Semantics |
|--------|-----------|
| `th.check(var, cond)` | Value satisfies condition **right now** |
| `th.check_stable(var, cond, duration)` | Condition holds for entire `duration` seconds |
| `th.check_until(var, cond, timeout)` | Condition becomes true **within** `timeout` seconds |
| `th.check_at(var, cond, at, tolerance)` | Condition first becomes true at `at` ± `tolerance` seconds |

**Runner**: Discovers all `@ammtest` functions under a path, runs each in sequence, writes one `.txt` result file per test. Result files include a full execution header (date, user, host, config, metadata), real-time log output, status, duration, and error details.

## Configuration

```jsonc
{
    "tests_path": "examples/tests",          // root used to compute relative paths in result files
    "results_path": "examples/results",      // directory where .txt result files are written
    "ammio_endpoint": "tcp://127.0.0.1:5555" // nng endpoint of the running ammio instance
}
```

## Related Projects

- **[ammio](https://github.com/ammonit-software/ammio)**: Protocol agnostic test interface for critical-software systems. Talk to any System Under Test (SUT) in JSON, regardless of its protocol.
- **[Ammonit Software](https://github.com/ammonit-software)**: Parent organization.

## License

This project is open source and available under the [MIT License](LICENSE).
