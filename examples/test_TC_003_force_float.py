"""
TC_003: Force Float Value

Description: Verify that float values can be forced and read.
Requirements: REQ-003
"""

from ammtest.client import AmmioClient


def test(client: AmmioClient):
    client.force("temperature", 25.5)

    value = client.read("temperature")
    assert value == 25.5
