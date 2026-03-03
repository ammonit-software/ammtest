VERSION = "0.1.0"
DESCRIPTION = "Verify that a signal value can be read from ammio"
REQUIREMENTS = [
    {"baseline": 1, "id": "REQ-001"},
    {"baseline": 1, "id": "REQ-002"},
]

import logging
import time

from ammtest.ammio import AmmioClient
from ammtest.config import CONFIG_PATH
from examples import utils


def test():

    # classes
    client = AmmioClient(CONFIG_PATH)

    # normalization
    utils.normalize(client)

    # initial checks
    assert client.read("IV_EC_CAB_STS") == 0
    assert client.read("IV_EC_CAB_A1_EN") == 0
    assert client.read("IV_EC_CAB_A2_EN") == 0
    assert client.read("IV_EC_CAB_CHANGE") == 0
    assert client.read("IV_EC_CAB_EN_IN_THIS_UT") == 0
    assert client.read("IV_EC_CAB_EN_IN_COMPO") == 0
    assert client.read("IV_EC_CAB_EN_IN_OTH_UT") == 0

    time.sleep(20000)

    value = client.read("train_life_signal")
    assert value is not None
    logging.info(f"Read train_life_signal: {value}")
    time.sleep(20)
    logging.info("Here")
