import json
import textwrap

import pytest

from ammtest.cli import main
from ammtest.runner import CollectionError, discover, run

HEADER = "from ammtest import ammtest, between\n\n"


def write(folder, name, body):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + textwrap.dedent(body))
    return path


@pytest.fixture
def suite(tmp_path):
    tests = tmp_path / "tests"
    write(tests, "_helpers.py", "def expect_on(sut, var):\n    sut.check(var, 1)\n")
    write(tests, "TC_001.py", """
        from _helpers import expect_on

        @ammtest(version="1.0", description="brake engages", requirements={"REQ-1": "A"})
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


# --- discovery --------------------------------------------------------------------


def test_discover_order_and_skips(suite):
    ids = [c.id for c in discover(suite)]
    assert ids == ["TC_001.py::test_brake", "sub/TC_002.py::test_fails", "sub/TC_002.py::test_error"]


def test_discover_single_file(suite):
    assert [c.id for c in discover(suite / "sub" / "TC_002.py")] == ["TC_002.py::test_fails", "TC_002.py::test_error"]


def test_discover_does_not_recollect_imported_tests(tmp_path):
    write(tmp_path, "a.py", "@ammtest()\ndef test_a(sut): pass\n")
    write(tmp_path, "b.py", "from a import test_a\n\n@ammtest()\ndef test_b(sut): pass\n")
    assert [c.id for c in discover(tmp_path)] == ["a.py::test_a", "b.py::test_b"]


def test_discover_sha256(suite):
    import hashlib

    case = discover(suite / "TC_001.py")[0]
    assert case.sha256 == hashlib.sha256((suite / "TC_001.py").read_bytes()).hexdigest()


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


# --- run --------------------------------------------------------------------------


def outputs(results):
    (run_dir,) = results.iterdir()
    return run_dir, json.loads((run_dir / "results.json").read_text())


def test_run_all_pass(ammio, tmp_path, suite):
    ammio.values.update(brake_request=0, brake_status=1, pressure=100)
    assert run(suite / "TC_001.py", ammio.endpoint, tmp_path / "results") == 0

    run_dir, data = outputs(tmp_path / "results")
    assert data["status"] == "PASS"
    assert data["totals"] == {"tests": 1, "passed": 1, "failed": 0, "errors": 0, "not_run": 0}
    test = data["tests"][0]
    assert test["requirements"] == {"REQ-1": "A"}
    assert test["checks_passed"] == 2 and test["checks_failed"] == 0

    report = (run_dir / test["report"]).read_text()
    assert "TC_001.py::test_brake" in report
    assert "REQ-1  [A]" in report
    assert f"File SHA-256:   {test['file_sha256']}" in report
    assert "WRITE  brake_request = 1" in report
    assert "PASS   brake_status = 1  [== 1]" in report
    assert "PASS   pressure = 100  [in [80, 120]]" in report
    assert "\033[" not in report
    assert (run_dir / "summary.txt").exists()


def test_run_fail_and_error(ammio, tmp_path, suite):
    ammio.values.update(brake_request=0, brake_status=1, pressure=100)
    assert run(suite, ammio.endpoint, tmp_path / "results") == 1

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
    assert "--- EXCEPTION ---" in error and "VAR_NOT_FOUND: does_not_exist" in error
    assert "TC_002.py" in error and "client.py" not in error  # only user frames


def test_plain_assert_is_a_fail(ammio, tmp_path):
    write(tmp_path, "t.py", "@ammtest()\ndef test(sut):\n    assert sut.read('x') == 2, 'x must be 2'\n")
    ammio.set("x", 1)
    assert run(tmp_path / "t.py", ammio.endpoint, tmp_path / "results") == 1
    assert outputs(tmp_path / "results")[1]["tests"][0]["status"] == "FAIL"


def test_connection_loss_aborts_run(ammio, tmp_path):
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


def test_run_no_tests(tmp_path):
    with pytest.raises(CollectionError, match="no @ammtest tests"):
        run(tmp_path, "inproc://unused")


# --- cli --------------------------------------------------------------------------


def test_cli_run_and_unreachable(ammio, tmp_path, suite, capsys):
    ammio.values.update(brake_request=0, brake_status=1, pressure=100)
    assert main(["run", str(suite / "TC_001.py"), "-e", ammio.endpoint, "-r", str(tmp_path / "r")]) == 0
    assert "1 tests: 1 passed, 0 failed, 0 errors" in capsys.readouterr().out

    assert main(["run", str(suite), "-e", "not-an-endpoint"]) == 2
    assert "ammtest: error:" in capsys.readouterr().err


def test_cli_collection_error(tmp_path, capsys):
    write(tmp_path, "t.py", "@ammtest()\ndef test(): pass\n")
    assert main(["trace", str(tmp_path)]) == 2
    assert "exactly one argument" in capsys.readouterr().err


def test_cli_unknown_option_is_rejected(suite):
    with pytest.raises(SystemExit) as e:
        main(["run", str(suite), "--result=out"])
    assert e.value.code == 2


def test_cli_vars(ammio, capsys):
    ammio.set("brake_status", 1)
    assert main(["vars", "-e", ammio.endpoint]) == 0
    assert "brake_status" in capsys.readouterr().out


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
