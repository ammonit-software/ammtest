import json
import logging
import time
from typing import Union

import pynng

from .exceptions import AmmioConnectionError, AmmioError

logger = logging.getLogger("ammtest")

CONNECTION_RETRIES = 3
CONNECTION_TIMEOUT_MS = 5000


class AmmioClient:
    """Client for communicating with ammio service."""

    def __init__(self, endpoint: str):
        """
        Initialize client and connect to ammio.

        Args:
            endpoint: nng endpoint to connect to (e.g. "tcp://127.0.0.1:5555")
        """
        self._endpoint = endpoint
        self._socket = None
        self._error_codes = {}
        self._connect()
        self._fetch_error_codes()

    def _connect(self) -> None:
        """Establish connection to ammio service with retries."""
        endpoint = self._endpoint
        if not endpoint:
            raise AmmioError("No endpoint provided")

        last_error = None
        for attempt in range(1, CONNECTION_RETRIES + 1):
            try:
                self._socket = pynng.Req0()
                self._socket.send_timeout = CONNECTION_TIMEOUT_MS
                self._socket.recv_timeout = CONNECTION_TIMEOUT_MS
                self._socket.dial(endpoint, block=True)
                return  # Success
            except (pynng.exceptions.ConnectionRefused, pynng.exceptions.Timeout) as e:
                last_error = e
                logger.warning(
                    f"Connection attempt {attempt}/{CONNECTION_RETRIES} failed: {e}"
                )
                if self._socket:
                    self._socket.close()
                    self._socket = None
                if attempt < CONNECTION_RETRIES:
                    time.sleep(1)  # Wait before retry
            except Exception as e:
                raise AmmioConnectionError(f"Connection failed: {e}")

        raise AmmioConnectionError(
            f"Cannot connect to ammio at {endpoint} after {CONNECTION_RETRIES} attempts: {last_error}"
        )

    def _send_request(self, request: dict) -> dict:
        """Send request and receive response."""
        if self._socket is None:
            raise AmmioConnectionError("Not connected to ammio")

        try:
            self._socket.send(json.dumps(request).encode())
            response = json.loads(self._socket.recv().decode())
            return response
        except pynng.exceptions.Timeout:
            raise AmmioConnectionError("Request timed out")
        except Exception as e:
            raise AmmioConnectionError(f"Communication error: {e}")

    def _fetch_error_codes(self) -> None:
        """Fetch error code definitions from ammio."""
        response = self._send_request({"cmd": "list_errors"})
        self._error_codes = response.get("errors", {})

    def _handle_response(self, response: dict, var_id: str) -> None:
        """Check response for errors."""
        error_code = response.get("error")
        if error_code is None:
            return

        error_name = self._error_codes.get(
            str(error_code), f"unknown error ({error_code})"
        )
        raise AmmioError(f"{error_name}: {var_id}")

    def list_vars(self) -> list[dict]:
        """Return the list of variables from ammio's var_table."""
        response = self._send_request({"cmd": "list_vars"})
        return response.get("vars", [])

    def write(
        self, var_id: str, value: Union[int, float, bool], quiet: bool = False
    ) -> None:
        """
        Write a value into the var_table.

        Args:
            var_id: Variable identifier
            value: Value to write

        Raises:
            AmmioError: If var_id not found or type mismatch
            AmmioConnectionError: If communication fails
        """
        response = self._send_request(
            {
                "cmd": "write",
                "name": var_id,
                "value": value,
            }
        )
        self._handle_response(response, var_id)
        if not quiet:
            logger.info(f"WRITE: {var_id} = {value}")

    def read(self, var_id: str, quiet: bool = False) -> Union[int, float, bool]:
        """
        Read current value from the var_table.

        Args:
            var_id: Variable identifier

        Returns:
            Current value of the variable

        Raises:
            AmmioError: If var_id not found
            AmmioConnectionError: If communication fails
        """
        response = self._send_request(
            {
                "cmd": "read",
                "name": var_id,
            }
        )
        self._handle_response(response, var_id)
        value = response.get("value")
        if not quiet:
            logger.info(f"READ: {var_id} = {value}")
        return value

    def copy(self) -> "AmmioClient":
        """Create an independent client connected to the same endpoint."""
        return AmmioClient(self._endpoint)

    def close(self) -> None:
        """Close connection to ammio."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None
