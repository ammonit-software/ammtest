"""
TC_001: Read Signal Value

Description: Verify that a signal value can be read from ammio.
Requirements: REQ-001
"""

import logging

from ammtest.client import AmmioClient


def test(client: AmmioClient):
    value = client.read("train_speed")
    assert value is not None
    logging.info(f"Read train_speed: {value}")
