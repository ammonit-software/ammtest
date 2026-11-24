"""Shared fixtures: an in-process fake ammio that mirrors the real ammio protocol.

Mirrors ammio's var_server: error codes and names, `input`/`output` directions
(outputs are read-only for clients), numeric-only writes (JSON booleans are
rejected as "missing value"), and C-cast storage per type.
"""

import json
import struct
import threading
import time
import uuid

import pynng
import pytest

INT_BITS = {"uint8": (8, False), "int8": (8, True), "uint16": (16, False),
            "int16": (16, True), "uint32": (32, False), "int32": (32, True)}


def c_cast(vtype, value):
    if vtype in INT_BITS:
        bits, signed = INT_BITS[vtype]
        v = int(value) & ((1 << bits) - 1)  # truncation + wrap, like a C cast
        return v - (1 << bits) if signed and v >= 1 << (bits - 1) else v
    if vtype == "float32":
        return struct.unpack("<f", struct.pack("<f", value))[0]
    return float(value)


class FakeAmmio:
    ERRORS = {"0": "ok", "1": "variable not found", "2": "read-only variable",
              "3": "invalid json", "4": "invalid command", "5": "missing value"}

    def __init__(self):
        self.endpoint = f"inproc://ammtest-{uuid.uuid4().hex}"
        self.values: dict = {}
        self.meta: dict = {}  # var_id -> (type, dir); default ("float64", "input")
        self.requests: list[dict] = []
        self._timers: list[threading.Timer] = []
        self._socket = pynng.Rep0(listen=self.endpoint, recv_timeout=50)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def define(self, var_id, value=0, type="float64", dir="input"):
        self.meta[var_id] = (type, dir)
        self.values[var_id] = value

    def set(self, var_id, value):
        """SUT side: set any variable, regardless of direction."""
        self.values[var_id] = value

    def set_later(self, delay, var_id, value):
        timer = threading.Timer(delay, self.set, (var_id, value))
        self._timers.append(timer)
        timer.start()

    def writes(self):
        return [(r["var_id"], r["value"]) for r in self.requests if r.get("cmd") == "write"]

    def _info(self, var_id):
        return self.meta.get(var_id, ("float64", "input"))

    def _handle(self, req: dict) -> dict:
        cmd, var_id = req.get("cmd"), req.get("var_id")
        if cmd == "list_errors":
            return {"errors": self.ERRORS}
        if cmd == "list_vars":
            return {"vars": [{"var_id": k, "type": self._info(k)[0], "dir": self._info(k)[1]}
                             for k in list(self.values)]}
        if cmd not in ("read", "write") or not isinstance(var_id, str):
            return {"error": 4}
        if var_id not in self.values:
            return {"error": 1}
        vtype, vdir = self._info(var_id)
        if cmd == "read":
            return {"var_id": var_id, "type": 0, "timestamp": time.time_ns(), "value": self.values[var_id]}
        if vdir == "output":
            return {"error": 2}
        value = req.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"error": 5}
        self.values[var_id] = c_cast(vtype, value)
        return {"status": "ok"}

    def _serve(self):
        while not self._stop.is_set():
            try:
                msg = self._socket.recv()
            except pynng.Timeout:
                continue
            except pynng.Closed:
                return
            req = json.loads(msg)
            self.requests.append(req)
            self._socket.send(json.dumps(self._handle(req)).encode())

    def close(self):
        for t in self._timers:
            t.cancel()
        self._stop.set()
        self._thread.join()
        self._socket.close()


@pytest.fixture
def ammio():
    fake = FakeAmmio()
    yield fake
    fake.close()


@pytest.fixture
def client(ammio):
    from ammtest import AmmioClient

    with AmmioClient(ammio.endpoint) as cl:
        yield cl


@pytest.fixture
def sut(client):
    from ammtest import Sut

    lines = []
    s = Sut(client, lambda text, style="": lines.append(text))
    s.lines = lines
    return s
