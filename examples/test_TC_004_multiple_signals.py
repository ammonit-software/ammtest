"""
TC_004: Multiple Signals Independence

Description: Verify that updating one signal does not affect others.
Requirements: REQ-004
"""

from ammtest.client import AmmioClient


def test_step_01(client: AmmioClient):
    """Set initial values"""
    client.force("train_speed", 80)
    client.force("temperature", 20.0)

    assert client.read("train_speed") == 80
    assert client.read("temperature") == 20.0


def test_step_02(client: AmmioClient):
    """Update one signal, verify other unchanged"""
    client.force("train_speed", 120)

    assert client.read("train_speed") == 120
    assert client.read("temperature") == 20.0
