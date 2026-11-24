import threading
import time

import pytest

from ammtest import AmmioClient, AmmioConnectionError, AmmioError, StaleValueError, between


# --- client -------------------------------------------------------------------


def test_client_read_write_list(ammio, client):
    ammio.define("x", 0, type="int16", dir="input")
    client.write("x", 5)
    assert client.read("x") == 5
    assert client.list_vars() == [{"var_id": "x", "type": "int16", "dir": "input"}]


def test_client_error_names_come_from_ammio(ammio, client):
    ammio.define("out", 1, dir="output")
    with pytest.raises(AmmioError, match="variable not found: nope"):
        client.read("nope")
    with pytest.raises(AmmioError, match="read-only variable: out"):
        client.write("out", 0)


def test_client_sends_booleans_as_numbers(ammio, client):
    ammio.define("flag", 0, type="uint8")
    client.write("flag", True)  # ammio rejects JSON true as "missing value"
    assert ammio.values["flag"] == 1


def test_client_cannot_connect():
    with pytest.raises(AmmioConnectionError, match="cannot connect"):
        AmmioClient("inproc://nobody-listens-here", retries=1)


def test_client_invalid_endpoint():
    with pytest.raises(AmmioConnectionError):
        AmmioClient("not-an-endpoint", retries=1)


# --- sut: io and immediate checks -----------------------------------------------


def test_write_read_log(ammio, sut):
    ammio.define("x", 0, type="int32")
    sut.write("x", 1)
    assert sut.read("x") == 1
    sut.log("step 2")
    assert sut.lines == ["WRITE  x = 1", "READ   x = 1", "NOTE   step 2"]


def test_unknown_variable_suggests_closest(ammio, sut):
    ammio.define("brake_status", 0)
    with pytest.raises(AmmioError, match="unknown variable 'brake_stauts' \\(did you mean 'brake_status'\\?\\)"):
        sut.check("brake_stauts", 1)
    assert ammio.requests[-1]["cmd"] == "list_vars"  # refused before reading


def test_variable_table_is_refreshed_for_new_names(ammio, sut):
    ammio.define("a", 1)
    sut.read("a")
    ammio.define("b", 2)  # appears after the table was fetched
    assert sut.read("b") == 2


def test_write_to_output_is_refused(ammio, sut):
    ammio.define("brake_status", 0, dir="output")
    with pytest.raises(AmmioError, match="SUT output"):
        sut.write("brake_status", 1)
    assert ammio.writes() == []


@pytest.mark.parametrize(
    "vtype, value, match",
    [
        ("uint8", 300, "uint8 range is \\[0, 255\\]"),  # ammio would store 44
        ("uint16", -1, "uint16 range"),
        ("int16", 1.7, "whole numbers"),  # ammio would store 1
        ("float32", 1e39, "float32 range"),
        ("float64", float("nan"), "finite number"),
        ("float64", "1", "finite number"),
    ],
)
def test_write_refuses_values_ammio_would_corrupt(ammio, sut, vtype, value, match):
    ammio.define("x", 0, type=vtype)
    with pytest.raises(ValueError, match=match):
        sut.write("x", value)
    assert ammio.writes() == []


def test_write_logs_what_is_actually_stored(ammio, sut):
    ammio.define("door", 0, type="uint8")
    ammio.define("volt", 0, type="float32")
    ammio.define("speed", 0, type="int32")
    sut.write("door", True)
    sut.write("volt", 0.1)
    sut.write("speed", 5.0)
    assert sut.lines == [
        "WRITE  door = True  (stored as uint8 1)",
        "WRITE  volt = 0.1  (stored as float32 0.10000000149011612)",
        "WRITE  speed = 5.0  (stored as int32 5)",
    ]
    assert ammio.values == {"door": 1, "volt": 0.10000000149011612, "speed": 5}


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


def test_snapshot(ammio, sut):
    ammio.define("b", 2, type="uint8", dir="output")
    ammio.define("a", 1.5)
    ammio.define("c", 0, dir="output")
    ammio.freeze("c", 30)
    (a, b, c) = sut._snapshot()
    assert a == ("a", "float64", "input", "1.5", "")  # inputs: no freshness
    assert b[:4] == ("b", "uint8", "output", "2") and b[4].startswith("age 0.0")
    assert c[4].startswith("STALE (age 30.")  # reported, never raised


# --- sut: stale values ------------------------------------------------------------


def test_client_read_sample_has_timestamp(ammio, client):
    ammio.define("x", 1, dir="output")
    value, stamp = client.read_sample("x")
    assert value == 1 and abs(time.time_ns() - stamp) < 1e9


def test_stale_output_is_an_error(ammio, sut):
    ammio.define("brake_status", 1, type="uint8", dir="output")
    assert sut.check("brake_status", 1)
    ammio.freeze("brake_status", 5)  # SUT stops publishing
    with pytest.raises(StaleValueError, match="'brake_status' is stale: last received from the SUT 5.0"):
        sut.check("brake_status", 1)
    with pytest.raises(StaleValueError):
        sut.read("brake_status")


def test_stale_during_timed_check(ammio, sut):
    ammio.define("x", 0, dir="output")
    threading.Timer(0.1, ammio.freeze, ("x", 10)).start()
    with pytest.raises(StaleValueError):
        sut.check_until("x", 1, timeout=1.0)


def test_inputs_are_not_checked_for_freshness(ammio, sut):
    ammio.define("cmd", 1, dir="input")
    ammio.freeze("cmd", 60)  # last written a minute ago: normal for an input
    assert sut.check("cmd", 1)


def test_never_received_and_future_timestamps(ammio, sut):
    ammio.define("x", 0, dir="output")
    ammio.stamps["x"] = 0  # ammio starts every value at timestamp 0
    with pytest.raises(StaleValueError, match="never been received"):
        sut.read("x")
    ammio.freeze("x", -10)
    with pytest.raises(StaleValueError, match="clocks? .*not synchronized"):
        sut.read("x")


def test_max_age_zero_disables_the_check(ammio, client):
    from ammtest import Sut

    ammio.define("x", 1, dir="output")
    ammio.freeze("x", 3600)
    assert Sut(client, lambda *a: None, max_age=0).check("x", 1)
    assert Sut(client, lambda *a: None, max_age=7200).check("x", 1)
    with pytest.raises(ValueError):
        Sut(client, max_age=-1)


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
