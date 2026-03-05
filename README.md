<p align="center">
  <img src="assets/ammtest.png" alt="ammtest" width="350"/>
</p>

<p align="center">
  <strong>Python test framework for safety-critical systems. Write, run, and trace system-level tests against any SUT via ammio.</strong>
</p>

# ammtest

**ammtest** is a Python test framework for testing safety-critical software systems. It connects to [ammio](https://github.com/ammonit-software/ammio) to interact with the System Under Test — writing inputs, reading outputs, and asserting behavior — with full traceability built in.

Every test is tagged with metadata (version, description, requirements) and produces a structured `.txt` result file per execution, ready for review or certification evidence.

## Quickstart

### Install

```bash
pip install ammtest
```

### Write a test

```python
from ammtest import ammtest, AmmioClient, AmmTestHelper

@ammtest(
    version="0.1.0",
    description="Verify brake engages when request is sent",
    requirements=["REQ-042"],
)
def test(cl: AmmioClient, th: AmmTestHelper):
    cl.write("brake_request", 1)
    th.check("brake_status", lambda v: v == 1)
    th.check_stable("brake_status", lambda v: v == 1, duration=2.0)
    th.check_until("brake_pressure", lambda v: v > 80, timeout=1.0)
    th.check_at("brake_pressure", lambda v: v > 80, at=0.5, tolerance=0.1)
```

### Run

```bash
ammtest run tests/
ammtest run tests/ --ammtest-config=config/config.json
```

Requires [ammio](https://github.com/ammonit-software/ammio) to be running.

## Architecture

**ammtest** discovers `@ammtest`-decorated functions, runs each against a live ammio instance, and writes result files to disk. No test framework overhead — plain Python functions, plain files.

```
  test functions (@ammtest decorator)
         │
         │  cl.write("var", value)                    →  force SUT inputs
         │  th.check("var", lambda v: v == 1)         ←  one-shot check
         │  th.check_stable("var", lambda v: ..., duration)   stability check
         │  th.check_until("var", lambda v: ..., timeout)     transition check
         │  th.check_at("var", lambda v: ..., at, tolerance)  timing check
         │
  ┌──────┴──────────────────────────────────────────────────────┐
  │                          ammtest                            │
  │  ┌──────────┐  ┌─────────────┐  ┌───────────────────────┐  │
  │  │ @ammtest │  │ AmmioClient │  │    AmmTestHelper       │  │
  │  │ metadata │  │ nng REQ/REP │  │  check / check_stable  │  │
  │  └──────────┘  └──────┬──────┘  │  check_until / check_at│  │
  │                        │         └───────────────────────┘  │
  │                   runner: discover, run, write results       │
  └────────────────────────│─────────────────────────────────────┘
                           │ nng REQ/REP · JSON · TCP
                           ▼
                         ammio → SUT
```

**`@ammtest` decorator**: Tags a function as a test case. Attaches `version`, `description`, and `requirements` as metadata directly on the function.

**`AmmioClient` (`cl`)**: Connects to ammio over nng REQ/REP. `write(var_id, value)` forces SUT inputs; `read(var_id)` observes SUT outputs. Errors from ammio are resolved to human-readable names and raised as `AmmioError`.

**`AmmTestHelper` (`th`)**: Injected as the second argument to each test function. Owns the client and provides four check methods — each reads the variable quietly, evaluates a lambda condition, and emits a single `CHECK PASS` / `CHECK FAIL` log line with the variable name, actual value, and condition expression.

| Method | Semantics |
|--------|-----------|
| `th.check(var, cond)` | Value satisfies condition **right now** |
| `th.check_stable(var, cond, duration)` | Condition holds for entire `duration` seconds |
| `th.check_until(var, cond, timeout)` | Condition becomes true **within** `timeout` seconds |
| `th.check_at(var, cond, at, tolerance)` | Condition first becomes true at `at` ± `tolerance` seconds |

**Runner**: Discovers all `@ammtest` functions under a path, runs each in sequence, writes one `.txt` result file per test. Result files include a full execution header (date, user, host, config, metadata), real-time log output, status, duration, and error details.

## Configuration

```json
{
    "results_path": "results",
    "ammio_endpoint": "tcp://127.0.0.1:5555"
}
```

| Field | Description |
|-------|-------------|
| `results_path` | Directory where `.txt` result files are written |
| `ammio_endpoint` | nng endpoint of the running ammio instance |

## Related Projects

- **[ammio](https://github.com/ammonit-software/ammio)**: Protocol-agnostic test interface that ammtest connects to for SUT interaction.
- **[Ammonit Software](https://github.com/ammonit-software)**: Parent organization.

## License

This project is open source and available under the [MIT License](LICENSE).
