import json
import logging
import time
from typing import Union

import pynng

from .exceptions import (
    AmmioConnectionError,
    AmmioError,
    SignalNotFoundError,
    SignalTypeError,
)

logger = logging.getLogger("ammtest")

CONNECTION_RETRIES = 3
CONNECTION_TIMEOUT_MS = 5000


class AmmioClient:
    """Client for communicating with ammio service."""

    def __init__(self, config_path: str):
        """
        Initialize client from config file.

        Args:
            config_path: Path to JSON config file containing endpoint
        """
        self._config = self._load_config(config_path)
        self._socket = None
        self._connect()

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        try:
            with open(config_path) as f:
                return json.load(f)
        except FileNotFoundError:
            raise AmmioError(f"Config file not found: {config_path}")
        except json.JSONDecodeError as e:
            raise AmmioError(f"Invalid JSON in config file: {e}")

    def _connect(self) -> None:
        """Establish connection to ammio service with retries."""
        endpoint = self._config.get("endpoint")
        if not endpoint:
            raise AmmioError("Config missing 'endpoint' field")

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
                logger.warning(f"Connection attempt {attempt}/{CONNECTION_RETRIES} failed: {e}")
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

    def _handle_response(self, response: dict, var_id: str) -> None:
        """Check response for errors."""
        if response.get("status") == "error":
            error_msg = response.get("message", "Unknown error")
            if "not found" in error_msg.lower():
                raise SignalNotFoundError(f"Signal not found: {var_id}")
            elif "type" in error_msg.lower():
                raise SignalTypeError(f"Type mismatch for signal: {var_id}")
            else:
                raise AmmioError(error_msg)

    def force(self, var_id: str, value: Union[int, float, bool]) -> None:
        """
        Force a value into the var_table.

        Args:
            var_id: Signal identifier
            value: Value to force

        Raises:
            SignalNotFoundError: If var_id not found
            SignalTypeError: If value type doesn't match
            AmmioConnectionError: If communication fails
        """
        logger.info(f"FORCE: {var_id} = {value}")
        response = self._send_request({
            "cmd": "write",
            "name": var_id,
            "value": value,
        })
        self._handle_response(response, var_id)

    def read(self, var_id: str) -> Union[int, float, bool]:
        """
        Read current value from the var_table.

        Args:
            var_id: Signal identifier

        Returns:
            Current value of the signal

        Raises:
            SignalNotFoundError: If var_id not found
            AmmioConnectionError: If communication fails
        """
        response = self._send_request({
            "cmd": "read",
            "name": var_id,
        })
        self._handle_response(response, var_id)
        value = response.get("value")
        logger.info(f"READ: {var_id} = {value}")
        return value

    def close(self) -> None:
        """Close connection to ammio."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None
