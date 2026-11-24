from ammtest import ammtest, between


@ammtest(
    description="Brake engages within 500 ms of a brake request and holds pressure",
    requirements={"REQ-1416": "A", "REQ-1418": "B"},
)
def test_brake_engages(sut):
    sut.write("brake_request", 1)
    sut.check_until("brake_status", 1, timeout=0.5)
    sut.check_stable("brake_pressure", between(80, 120), duration=1.0)
