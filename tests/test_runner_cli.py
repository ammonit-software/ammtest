import hashlib
import json
import shutil
import subprocess
import textwrap

import pytest

from ammtest.cli import main
from ammtest.runner import CollectionError, discover, run

HEADER = "from ammtest import ammtest, between\n\n"

SAFE_STATE = """
def safe_state(sut):
    sut.write("brake_request", 1)
"""


def write(folder, name, body, header=HEADER):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + textwrap.dedent(body))
    return path


@pytest.fixture
def suite(tmp_path):
    tests = tmp_path / "tests"
    write(tests, "_helpers.py", "def expect_on(sut, var):\n    sut.check(var, 1)\n")
    write(tests, "TC_001.py", """
        from _helpers import expect_on

        @ammtest(description="brake engages", requirements={"REQ-1": "A"})
        def test_brake(sut):
            sut.write("brake_request", 1)
            expect_on(sut, "brake_status")
            sut.check("pressure", between(80, 120))

        def not_a_test(sut):
            raise RuntimeError("must not run")
        """)
    write(tests, "sub/TC_002.py", """
        @ammtest(requirements={"REQ-2": "B", "REQ-9": "A"})
        def test_fails(sut):
            sut.check("brake_status", 0)
            sut.check("pressure", 100)

        @ammtest()
        def test_error(sut):
            sut.read("does_not_exist")
        """)
    write(tests, ".hidden/TC_003.py", "@ammtest()\ndef test_hidden(sut): pass\n")
    return tests


@pytest.fixture
def sut_vars(ammio):
    ammio.define("brake_request", 0, type="uint8", dir="input")
    ammio.define("brake_status", 1, type="uint8", dir="output")
    ammio.define("pressure", 100, type="float32", dir="output")
    return ammio


def outputs(results):
    (run_dir,) = results.iterdir()
    return run_dir, json.loads((run_dir / "results.json").read_text())


# --- discovery --------------------------------------------------------------------


def test_discover_order_and_skips(suite):
    ids = [c.id for c in discover(suite)]
    assert ids == ["TC_001.py::test_brake", "sub/TC_002.py::test_fails", "sub/TC_002.py::test_error"]


def test_discover_single_file(suite):
    assert [c.id for c in discover(suite / "sub" / "TC_002.py")] == ["TC_002.py::test_fails", "TC_002.py::test_error"]


def test_discover_single_test(suite):
    assert [c.id for c in discover(f"{suite / 'sub' / 'TC_002.py'}::test_error")] == ["TC_002.py::test_error"]
    with pytest.raises(CollectionError, match="no @ammtest test named 'nope'"):
        discover(f"{suite / 'TC_001.py'}::nope")


def test_discover_does_not_recollect_imported_tests(tmp_path):
    write(tmp_path, "a.py", "@ammtest()\ndef test_a(sut): pass\n")
    write(tmp_path, "b.py", "from a import test_a\n\n@ammtest()\ndef test_b(sut): pass\n")
    assert [c.id for c in discover(tmp_path)] == ["a.py::test_a", "b.py::test_b"]


def test_discover_sha256(suite):
    case = discover(suite / "TC_001.py")[0]
    assert case.sha256 == hashlib.sha256((suite / "TC_001.py").read_bytes()).hexdigest()


def test_discover_nearest_safe_state(suite):
    write(suite, "_safe_state.py", SAFE_STATE, header="")
    write(suite, "sub/_safe_state.py", SAFE_STATE + "\n# sub\n", header="")
    by_id = {c.id: c.safe_state.path for c in discover(suite)}
    assert by_id["TC_001.py::test_brake"] == suite / "_safe_state.py"
    assert by_id["sub/TC_002.py::test_fails"] == suite / "sub" / "_safe_state.py"
    # a single file still finds the safe state of its parent folders
    assert discover(suite / "TC_001.py")[0].safe_state.path == suite / "_safe_state.py"


@pytest.mark.parametrize(
    "body, match",
    [
        ("@ammtest()\ndef test(sut, other): pass\n", "exactly one argument"),
        ("def broken(:\n", "cannot import"),
        ("@ammtest(requirements=['REQ-1'])\ndef test(sut): pass\n", "cannot import"),
    ],
)
def test_collection_errors(tmp_path, body, match):
    write(tmp_path, "TC_bad.py", body)
    with pytest.raises(CollectionError, match=match):
        discover(tmp_path)


def test_bad_safe_state_is_a_collection_error(tmp_path):
    write(tmp_path, "t.py", "@ammtest()\ndef test(sut): pass\n")
    write(tmp_path, "_safe_state.py", "def safe(sut): pass\n", header="")
    with pytest.raises(CollectionError, match="safe_state\\(sut\\)"):
        discover(tmp_path)


# --- run --------------------------------------------------------------------------


def test_run_all_pass(sut_vars, tmp_path, suite, capsys):
    assert run(suite / "TC_001.py", sut_vars.endpoint, tmp_path / "results") == 0

    run_dir, data = outputs(tmp_path / "results")
    assert data["status"] == "PASS"
    assert data["totals"] == {"tests": 1, "passed": 1, "failed": 0, "errors": 0, "not_run": 0}
    assert data["final_safe_state"] is None
    test = data["tests"][0]
    assert test["requirements"] == {"REQ-1": "A"}
    assert test["checks_passed"] == 2 and test["checks_failed"] == 0
    assert test["git"] is None  # tmp folder is not a git repository

    report_path = run_dir / test["report"]
    assert test["report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    report = report_path.read_text()
    assert "TC_001.py::test_brake" in report
    assert "REQ-1  [A]" in report
    assert f"File SHA-256:   {test['file_sha256']}" in report
    assert "Git:            (not under git)" in report
    assert "Safe state:     (none)" in report
    assert "--- INITIAL STATE ---\n\n  brake_request  uint8    input   0\n" in report
    assert "WRITE  brake_request = 1" in report
    assert "PASS   brake_status = 1  [== 1]" in report
    assert "PASS   pressure = 100  [in [80, 120]]" in report
    assert "\033[" not in report
    assert (run_dir / "summary.txt").exists()

    out = capsys.readouterr().out  # compact terminal output: no log lines
    assert "TC_001.py::test_brake ... PASS" in out
    assert "WRITE" not in out


def test_run_verbose_streams_report(sut_vars, tmp_path, suite, capsys):
    assert run(suite / "TC_001.py", sut_vars.endpoint, tmp_path / "results", verbose=True) == 0
    out = capsys.readouterr().out
    assert "AMMTEST EXECUTION REPORT" in out and "WRITE  brake_request = 1" in out


def test_run_fail_and_error(sut_vars, tmp_path, suite, capsys):
    assert run(suite, sut_vars.endpoint, tmp_path / "results") == 1

    run_dir, data = outputs(tmp_path / "results")
    statuses = {t["id"]: t["status"] for t in data["tests"]}
    assert statuses == {
        "TC_001.py::test_brake": "PASS",
        "sub/TC_002.py::test_fails": "FAIL",
        "sub/TC_002.py::test_error": "ERROR",
    }
    fails = (run_dir / "sub" / "TC_002.test_fails.txt").read_text()
    assert "Checks:         1 passed, 1 failed" in fails
    assert "[1] check: brake_status = 1  [== 0]" in fails
    assert 'TC_002.py:6  sut.check("brake_status", 0)' in fails
    error = (run_dir / "sub" / "TC_002.test_error.txt").read_text()
    assert "--- EXCEPTION ---" in error and "unknown variable 'does_not_exist'" in error
    assert "TC_002.py" in error and "sut.py" not in error  # only user frames

    out = capsys.readouterr().out  # compact mode still shows why tests failed
    assert "sub/TC_002.py::test_fails ... FAIL" in out
    assert "check: brake_status = 1  [== 0]" in out
    assert "unknown variable 'does_not_exist'" in out


def test_plain_assert_is_a_fail(ammio, tmp_path):
    write(tmp_path, "t.py", "@ammtest()\ndef test(sut):\n    assert sut.read('x') == 2, 'x must be 2'\n")
    ammio.set("x", 1)
    assert run(tmp_path / "t.py", ammio.endpoint, tmp_path / "results") == 1
    assert outputs(tmp_path / "results")[1]["tests"][0]["status"] == "FAIL"


def test_connection_loss_aborts_run(ammio, tmp_path):
    ammio.set("brake_request", 0)
    write(tmp_path, "_safe_state.py", SAFE_STATE, header="")
    write(tmp_path, "t.py", """
        from ammtest import AmmioConnectionError

        @ammtest()
        def test_1(sut):
            raise AmmioConnectionError("gone")

        @ammtest()
        def test_2(sut):
            pass
        """)
    assert run(tmp_path / "t.py", ammio.endpoint, tmp_path / "results") == 2
    data = outputs(tmp_path / "results")[1]
    assert data["status"] == "ERROR"
    assert data["not_run"] == ["t.py::test_2"]
    assert "connection to ammio lost" in data["aborted"]
    assert data["final_safe_state"] == "NOT APPLIED: connection lost"


def test_stale_output_makes_the_test_an_error(sut_vars, tmp_path, suite, capsys):
    sut_vars.freeze("brake_status", 5)
    assert run(suite / "TC_001.py", sut_vars.endpoint, tmp_path / "r1") == 1
    run_dir, data = outputs(tmp_path / "r1")
    assert data["tests"][0]["status"] == "ERROR"
    assert data["max_value_age_s"] == 1.0
    report = (run_dir / data["tests"][0]["report"]).read_text()
    assert "Max value age:  1.0s (older SUT outputs are an ERROR)" in report
    assert "brake_status   uint8    output  1    STALE (age 5." in report
    assert "'brake_status' is stale" in report

    # explicitly disabled: recorded in the evidence
    assert main(["run", str(suite / "TC_001.py"), "-e", sut_vars.endpoint, "-r", str(tmp_path / "r2"),
                 "--max-age", "0"]) == 0
    run_dir, data = outputs(tmp_path / "r2")
    assert data["max_value_age_s"] == 0
    assert "Max value age:  not checked" in (run_dir / data["tests"][0]["report"]).read_text()


def test_max_age_from_env_and_validation(monkeypatch, capsys):
    from ammtest.cli import _parser

    monkeypatch.setenv("AMMTEST_MAX_AGE", "2.5")
    assert _parser().parse_args(["run", "x"]).max_age == 2.5
    monkeypatch.setenv("AMMTEST_MAX_AGE", "soon")
    with pytest.raises(SystemExit) as e:
        _parser().parse_args(["run", "x"])
    assert e.value.code == 2


def test_no_variables_in_ammio(ammio, tmp_path):
    write(tmp_path, "t.py", "@ammtest()\ndef test(sut): pass\n")
    with pytest.raises(Exception, match="exposes no variables"):
        run(tmp_path, ammio.endpoint, tmp_path / "results")


def test_run_no_tests(tmp_path):
    with pytest.raises(CollectionError, match="no @ammtest tests"):
        run(tmp_path, "inproc://unused")


# --- safe state -------------------------------------------------------------------


def test_safe_state_before_each_test_and_at_end(sut_vars, tmp_path, suite):
    write(suite, "_safe_state.py", SAFE_STATE, header="")
    assert run(suite, sut_vars.endpoint, tmp_path / "results") == 1  # TC_002 fails as usual

    run_dir, data = outputs(tmp_path / "results")
    assert data["final_safe_state"] == "applied"
    # 3 tests + end of run; test_brake writes once more itself
    assert sut_vars.writes().count(("brake_request", 1)) == 5
    report = (run_dir / "TC_001.test_brake.txt").read_text()
    assert report.index("--- SAFE STATE ---") < report.index("--- INITIAL STATE ---") < report.index("--- LOG ---")
    assert f"Safe state SHA: {data['tests'][0]['safe_state']['sha256']}" in report
    end = (run_dir / "safe_state.txt").read_text()
    assert "WRITE  brake_request = 1" in end and "APPLIED" in end


def test_failing_safe_state_aborts(sut_vars, tmp_path, suite):
    write(suite, "_safe_state.py", "def safe_state(sut):\n    sut.check('brake_status', 0)\n", header="")
    assert run(suite, sut_vars.endpoint, tmp_path / "results") == 2

    run_dir, data = outputs(tmp_path / "results")
    assert [t["status"] for t in data["tests"]] == ["ERROR"]
    assert data["not_run"] == ["sub/TC_002.py::test_fails", "sub/TC_002.py::test_error"]
    assert "safe state failed before TC_001.py::test_brake" in data["aborted"]
    assert data["final_safe_state"] == "NOT APPLIED: safe state failed"
    report = (run_dir / "TC_001.test_brake.txt").read_text()
    assert "safe state failed, test not run" in report and "--- LOG ---" not in report
    assert ("brake_request", 1) not in sut_vars.writes()  # the test itself never ran


def test_ctrl_c_still_applies_safe_state(sut_vars, tmp_path):
    write(tmp_path, "_safe_state.py", "def safe_state(sut):\n    sut.write('brake_request', 1)\n", header="")
    write(tmp_path, "t.py", """
        @ammtest()
        def test_1(sut):
            sut.write("brake_request", 0)
            raise KeyboardInterrupt

        @ammtest()
        def test_2(sut):
            pass
        """)
    assert run(tmp_path / "t.py", sut_vars.endpoint, tmp_path / "results") == 2
    data = outputs(tmp_path / "results")[1]
    assert data["aborted"] == "interrupted by user"
    assert data["final_safe_state"] == "applied"
    assert sut_vars.values["brake_request"] == 1


def test_failing_final_safe_state_is_an_error(sut_vars, tmp_path):
    write(tmp_path, "_safe_state.py", "def safe_state(sut):\n    sut.check('brake_request', 0)\n", header="")
    write(tmp_path, "t.py", "@ammtest()\ndef test(sut):\n    sut.write('brake_request', 1)\n")
    assert run(tmp_path / "t.py", sut_vars.endpoint, tmp_path / "results") == 2
    data = outputs(tmp_path / "results")[1]
    assert data["tests"][0]["status"] == "PASS"
    assert data["status"] == "ERROR"
    assert data["final_safe_state"].startswith("FAILED: 1 check(s) failed")


# --- git --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_state_recorded(ammio, tmp_path, capsys):
    ammio.set("x", 1)
    repo = tmp_path / "repo"
    test_file = write(repo, "t.py", "@ammtest()\ndef test(sut):\n    sut.check('x', 1)\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "t.py"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "test"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    assert run(test_file, ammio.endpoint, tmp_path / "r1") == 0
    run_dir, data = outputs(tmp_path / "r1")
    assert data["tests"][0]["git"] == {"commit": head, "committed": True}
    assert data["uncommitted_files"] == []
    assert f"Git:            {head}  (committed)" in (run_dir / data["tests"][0]["report"]).read_text()
    capsys.readouterr()

    test_file.write_text(test_file.read_text() + "# local edit\n")
    assert run(test_file, ammio.endpoint, tmp_path / "r2") == 0
    run_dir, data = outputs(tmp_path / "r2")
    assert data["tests"][0]["git"] == {"commit": head, "committed": False}
    assert len(data["uncommitted_files"]) == 1
    assert "(UNCOMMITTED CHANGES)" in (run_dir / data["tests"][0]["report"]).read_text()
    assert "Warning: uncommitted changes in" in capsys.readouterr().out


# --- cli --------------------------------------------------------------------------


def test_cli_run_and_unreachable(sut_vars, tmp_path, suite, capsys):
    assert main(["run", str(suite / "TC_001.py"), "-e", sut_vars.endpoint, "-r", str(tmp_path / "r")]) == 0
    assert "1 tests: 1 passed, 0 failed, 0 errors" in capsys.readouterr().out

    assert main(["run", str(suite), "-e", "not-an-endpoint"]) == 2
    assert "ammtest: error:" in capsys.readouterr().err


def test_cli_run_single_test(sut_vars, tmp_path, suite, capsys):
    target = f"{suite / 'sub' / 'TC_002.py'}::test_fails"
    assert main(["run", target, "-e", sut_vars.endpoint, "-r", str(tmp_path / "r")]) == 1
    assert [t["id"] for t in outputs(tmp_path / "r")[1]["tests"]] == ["TC_002.py::test_fails"]


def test_cli_collection_error(tmp_path, capsys):
    write(tmp_path, "t.py", "@ammtest()\ndef test(): pass\n")
    assert main(["trace", str(tmp_path)]) == 2
    assert "exactly one argument" in capsys.readouterr().err


def test_cli_unknown_option_is_rejected(suite):
    with pytest.raises(SystemExit) as e:
        main(["run", str(suite), "--result=out"])
    assert e.value.code == 2


def test_cli_vars(ammio, capsys):
    ammio.define("brake_status", 1, type="uint8", dir="output")
    assert main(["vars", "-e", ammio.endpoint]) == 0
    assert "brake_status  uint8  output" in capsys.readouterr().out


def test_cli_endpoint_from_env(monkeypatch):
    from ammtest.cli import _parser

    monkeypatch.setenv("AMMTEST_ENDPOINT", "tcp://10.0.0.1:1234")
    assert _parser().parse_args(["run", "x"]).endpoint == "tcp://10.0.0.1:1234"


def test_cli_trace_tests(suite, capsys):
    assert main(["trace", str(suite)]) == 1  # test_error has no requirements
    out = capsys.readouterr().out
    assert "TC_001.py::test_brake" in out and "REQ-1 [A]" in out
    assert "3 test(s), 1 without requirements" in out


def test_cli_trace_reqs(suite, tmp_path, capsys):
    reqs = tmp_path / "reqs.csv"
    reqs.write_text("﻿id;title\nREQ-1;brake\nREQ-2;release\nREQ-3;not covered\n", encoding="utf-8")
    args = ["trace", str(suite), "--reqs", str(reqs), "--delimiter", ";", "--skip-header"]
    assert main(args) == 1
    out = capsys.readouterr().out
    assert "REQ-1        TC_001.py::test_brake [A]" in out
    assert "REQ-3        (not covered)" in out
    assert "3 requirement(s), 1 not covered" in out
    assert "REQ-9  <- sub/TC_002.py::test_fails [A]" in out  # referenced but not in the CSV


def test_cli_trace_reqs_complete(tmp_path, capsys):
    write(tmp_path / "t", "t.py", "@ammtest(requirements={'REQ-1': 'A'})\ndef test(sut): pass\n")
    (tmp_path / "reqs.txt").write_text("REQ-1\n")
    assert main(["trace", str(tmp_path / "t"), "--reqs", str(tmp_path / "reqs.txt")]) == 0
