import time

import pytest

from ammtest import AmmioClient, AmmioConnectionError, AmmioError, between


# --- client -------------------------------------------------------------------


def test_client_read_write_list(ammio, client):
    ammio.set("x", 0)
    client.write("x", 5)
    assert client.read("x") == 5
    assert client.list_vars() == [{"var_id": "x", "type": "int", "dir": "inout"}]


def test_client_unknown_variable_uses_ammio_error_name(client):
    with pytest.raises(AmmioError, match="VAR_NOT_FOUND: nope"):
        client.read("nope")


def test_client_cannot_connect():
    with pytest.raises(AmmioConnectionError, match="cannot connect"):
        AmmioClient("inproc://nobody-listens-here", retries=1)


def test_client_invalid_endpoint():
    with pytest.raises(AmmioConnectionError):
        AmmioClient("not-an-endpoint", retries=1)


# --- sut: io and immediate checks -----------------------------------------------


def test_write_read_log(ammio, sut):
    ammio.set("x", 0)
    sut.write("x", 1)
    assert sut.read("x") == 1
    sut.log("step 2")
    assert sut.lines == ["WRITE  x = 1", "READ   x = 1", "NOTE   step 2"]


def test_check_pass_and_fail_location(ammio, sut):
    ammio.set("x", 1)
    assert sut.check("x", 1) is True
    assert sut.check("x", between(2, 3)) is False  # FAIL-LINE
    assert sut.passed == 1
    assert sut.lines == ["PASS   x = 1  [== 1]", "FAIL   x = 1  [in [2, 3]]"]
    (fail,) = sut.failures
    assert fail.message == "check: x = 1  [in [2, 3]]"
    assert fail.file.endswith("test_client_sut.py")
    assert "FAIL-LINE" in fail.source


def test_failure_location_through_user_helper(ammio, sut):
    ammio.set("x", 0)

    def expect_on(s, var):
        s.check(var, 1)  # HELPER-LINE

    expect_on(sut, "x")
    assert "HELPER-LINE" in sut.failures[0].source


def test_unknown_variable_raises(sut):
    with pytest.raises(AmmioError):
        sut.check("nope", 1)


def test_negative_durations_rejected(ammio, sut):
    ammio.set("x", 1)
    for call in (
        lambda: sut.wait(-1),
        lambda: sut.check_until("x", 1, timeout=-1),
        lambda: sut.check_stable("x", 1, duration=-1),
        lambda: sut.check_at("x", 1, at=1, tolerance=-1),
    ):
        with pytest.raises(ValueError):
            call()


# --- sut: timed checks ------------------------------------------------------------


def test_check_until_passes_when_reached(ammio, sut):
    ammio.set("x", 0)
    ammio.set_later(0.2, "x", 1)
    t0 = time.monotonic()
    assert sut.check_until("x", 1, timeout=1.0)
    assert 0.15 < time.monotonic() - t0 < 0.6


def test_check_until_times_out(ammio, sut):
    ammio.set("x", 0)
    t0 = time.monotonic()
    assert not sut.check_until("x", 1, timeout=0.2)
    assert 0.2 <= time.monotonic() - t0 < 0.5
    assert "not reached within 0.2s" in sut.failures[0].message


def test_check_stable_holds(ammio, sut):
    ammio.set("x", 1)
    t0 = time.monotonic()
    assert sut.check_stable("x", 1, duration=0.2)
    assert time.monotonic() - t0 >= 0.2  # sampled up to the end of the window


def test_check_stable_breaks(ammio, sut):
    ammio.set("x", 1)
    ammio.set_later(0.1, "x", 0)
    assert not sut.check_stable("x", 1, duration=1.0)
    assert "broke after" in sut.failures[0].message


def test_check_at_in_window(ammio, sut):
    ammio.set("x", 0)
    ammio.set_later(0.3, "x", 1)
    assert sut.check_at("x", 1, at=0.3, tolerance=0.15)


def test_check_at_too_early(ammio, sut):
    ammio.set("x", 0)
    ammio.set_later(0.05, "x", 1)
    assert not sut.check_at("x", 1, at=0.5, tolerance=0.1)
    assert "too early" in sut.failures[0].message


def test_check_at_already_true_is_too_early(ammio, sut):
    ammio.set("x", 1)
    assert not sut.check_at("x", 1, at=0.5, tolerance=0.1)


def test_check_at_never(ammio, sut):
    ammio.set("x", 0)
    assert not sut.check_at("x", 1, at=0.1, tolerance=0.05)
    assert "no transition" in sut.failures[0].message
