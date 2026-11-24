"""Shared fixtures: an in-process fake ammio speaking the real JSON protocol."""

import json
import threading
import uuid

import pynng
import pytest


class FakeAmmio:
    ERRORS = {"1": "VAR_NOT_FOUND"}

    def __init__(self):
        self.endpoint = f"inproc://ammtest-{uuid.uuid4().hex}"
        self.values: dict = {}
        self.requests: list[dict] = []
        self._timers: list[threading.Timer] = []
        self._socket = pynng.Rep0(listen=self.endpoint, recv_timeout=50)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def set(self, var_id, value):
        self.values[var_id] = value

    def set_later(self, delay, var_id, value):
        timer = threading.Timer(delay, self.set, (var_id, value))
        self._timers.append(timer)
        timer.start()

    def _handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "list_errors":
            return {"errors": self.ERRORS}
        if cmd == "list_vars":
            return {"vars": [{"var_id": k, "type": type(v).__name__, "dir": "inout"} for k, v in self.values.items()]}
        if req.get("var_id") not in self.values:
            return {"error": 1}
        if cmd == "read":
            return {"value": self.values[req["var_id"]]}
        if cmd == "write":
            self.values[req["var_id"]] = req["value"]
            return {}
        return {"error": 99}

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
