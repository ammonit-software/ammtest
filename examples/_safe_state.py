"""Safe state: applied before every test and at the end of the run (also after Ctrl+C)."""


def safe_state(sut):
    sut.write("brake_request", 0)
    sut.check_until("brake_status", 0, timeout=1.0)
