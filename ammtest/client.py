"""Transport to ammio: one JSON request, one JSON reply, over an nng REQ socket."""

import json
import time

import pynng

Value = int | float | bool


class AmmioError(Exception):
    """ammio rejected a request (unknown variable, type mismatch, ...)."""


class AmmioConnectionError(AmmioError):
    """ammio is unreachable, stopped answering, or answered garbage."""


class AmmioClient:
    """Minimal ammio client.

    Used by the runner, but also usable on its own::

        with AmmioClient("tcp://127.0.0.1:5555") as cl:
            cl.write("brake_request", 1)
            print(cl.read("brake_status"))
    """

    def __init__(self, endpoint: str, timeout: float = 5.0, retries: int = 3):
        self.endpoint = endpoint
        self.timeout = timeout
        ms = int(timeout * 1000)
        self._socket = pynng.Req0(send_timeout=ms, recv_timeout=ms)
        try:
            self._dial(retries)
            self._errors = self._request({"cmd": "list_errors"}).get("errors", {})
        except BaseException:
            self._socket.close()
            raise

    def _dial(self, retries: int) -> None:
        for attempt in range(1, retries + 1):
            try:
                self._socket.dial(self.endpoint, block=True)
                return
            except (pynng.ConnectionRefused, pynng.Timeout) as e:
                if attempt == retries:
                    raise AmmioConnectionError(
                        f"cannot connect to ammio at {self.endpoint} "
                        f"({retries} attempt(s)): {e}"
                    ) from e
                time.sleep(1)
            except pynng.NNGException as e:
                raise AmmioConnectionError(f"invalid ammio endpoint {self.endpoint!r}: {e}") from e

    def _request(self, request: dict) -> dict:
        try:
            self._socket.send(json.dumps(request).encode())
            reply = json.loads(self._socket.recv())
        except pynng.Timeout as e:
            raise AmmioConnectionError(f"ammio did not answer within {self.timeout}s") from e
        except pynng.NNGException as e:
            raise AmmioConnectionError(f"communication with ammio failed: {e}") from e
        except ValueError as e:
            raise AmmioConnectionError(f"invalid reply from ammio: {e}") from e
        if not isinstance(reply, dict):
            raise AmmioConnectionError(f"invalid reply from ammio: {reply!r}")
        code = reply.get("error")
        if code is not None:
            name = self._errors.get(str(code), f"error {code}")
            raise AmmioError(f"{name}: {request.get('var_id', request['cmd'])}")
        return reply

    def read(self, var_id: str) -> Value:
        """Return the current value of `var_id`."""
        reply = self._request({"cmd": "read", "var_id": var_id})
        if "value" not in reply:
            raise AmmioConnectionError(f"ammio reply to read {var_id!r} has no value")
        return reply["value"]

    def write(self, var_id: str, value: Value) -> None:
        """Force `var_id` to `value`. ammio only takes numbers, so booleans are sent as 1/0."""
        if isinstance(value, bool):
            value = int(value)
        self._request({"cmd": "write", "var_id": var_id, "value": value})

    def list_vars(self) -> list[dict]:
        """Return ammio's variable table: dicts with `var_id`, `type` and `dir`."""
        return self._request({"cmd": "list_vars"}).get("vars", [])

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> "AmmioClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
