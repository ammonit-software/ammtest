import logging
import re
import time
from functools import wraps
from threading import Thread

from ammtest.ammio import AmmioClient


def thread(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        thread = Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()

        return thread

    return wrapper


@thread
def simulate_life_signs(client: AmmioClient, life_signs: list, counter: int = 0):
    time.sleep(0.1)

    counter = 0 if counter == 255 else counter + 1
    for life_sign in life_signs:
        client.force(life_sign, counter, quiet=True)

    simulate_life_signs(client, life_signs, counter)


def normalize(client: AmmioClient):

    logging.info("force all inputs to 0")
    logging.info("force all check variables to 1")
    logging.info("simulate all life signs incrementaly via threads")

    vars = client.list_vars()
    life_signs = []
    for var in vars:
        if var["dir"] == "input":
            if re.match("\\w+_CV$", var["name"]):
                client.force(var["name"], 1, quiet=True)
            elif re.match("(\\w+(LFW|LIFEWORD|HEARTBEAT|LifeW|LIFEB).*$)", var["name"]):
                life_signs.append(var["name"])
            else:
                client.force(var["name"], 0, quiet=True)
    simulate_life_signs(client, life_signs)
    time.sleep(1)
