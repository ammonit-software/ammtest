"""
TC_002: Force and Read Signal

Description: Verify that a forced value can be read back.
Requirements: REQ-002
"""

from ammtest.client import AmmioClient


def test(client: AmmioClient):
    client.force("train_speed", 100)

    value = client.read("train_speed")
    assert value == 100
