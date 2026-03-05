import inspect
import logging
import time

from ammtest.ammio import AmmioClient
from ammtest.exceptions import _CheckFailures

logger = logging.getLogger("ammtest")


class AmmTestHelper:
    """
    Test helper — injected into test functions as the second argument.

    Provides traced assertions and test automation helpers.

    Usage:
        @ammtest(...)
        def test(cl: AmmioClient, th: AmmTestHelper):
            th.check("signal", lambda v: v == 0)
            th.check_stable("signal", lambda v: v == 1, duration=2.0)
            th.check_until("signal", lambda v: v == 1, timeout=2.0)
            th.check_at("signal", lambda v: v == 1, at=2.0, tolerance=0.1)

    Checks are soft: failures are collected and the test continues.
    finalize() is called automatically by the runner at the end.
    """

    def __init__(self, cl: AmmioClient):
        self.cl = cl
        self._failures = []

    def _record_failure(self, msg: str) -> None:
        """Capture caller location and append failure to the list."""
        frame = inspect.stack()[2]  # 0=_record_failure, 1=check_*, 2=test function
        source = frame.code_context[0].strip() if frame.code_context else "?"
        self._failures.append({
            "msg": msg,
            "file": frame.filename,
            "lineno": frame.lineno,
            "source": source,
        })

    def finalize(self) -> None:
        """Raise _CheckFailures if any checks failed. Details are reported by the runner."""
        if self._failures:
            raise _CheckFailures(self._failures)

    def check(self, var_id: str, condition) -> None:
        """Read var_id once and assert condition against the value."""
        value = self.cl.read(var_id, quiet=True)
        result = condition(value)
        expr = self._condition_expr()

        if result:
            logger.info(f"CHECK PASS  {var_id} = {value}  [{expr}]")
        else:
            logger.error(f"CHECK FAIL  {var_id} = {value}  [{expr}]")
            self._record_failure(f"check failed: {var_id} = {value}  [{expr}]")

    def check_stable(self, var_id: str, condition, duration: float, interval: float = 0.05) -> None:
        """Assert that condition holds continuously for the entire duration."""
        expr = self._condition_expr()
        deadline = time.monotonic() + duration
        value = None

        while time.monotonic() < deadline:
            value = self.cl.read(var_id, quiet=True)
            if not condition(value):
                logger.error(f"CHECK FAIL  {var_id} = {value}  [{expr}]  broke before {duration}s")
                self._record_failure(f"check_stable failed: {var_id} = {value}  [{expr}]")
                return
            time.sleep(interval)

        logger.info(f"CHECK PASS  {var_id} = {value}  [{expr}]  stable for {duration}s")

    def check_until(self, var_id: str, condition, timeout: float, interval: float = 0.05) -> None:
        """Assert that condition becomes true within timeout seconds."""
        expr = self._condition_expr()
        start = time.monotonic()
        value = None

        while True:
            elapsed = time.monotonic() - start
            value = self.cl.read(var_id, quiet=True)

            if condition(value):
                logger.info(f"CHECK PASS  {var_id} = {value}  [{expr}]  after {elapsed:.3f}s")
                return

            if elapsed >= timeout:
                logger.error(f"CHECK FAIL  {var_id} = {value}  [{expr}]  timed out after {timeout}s")
                self._record_failure(f"check_until failed: {var_id} = {value}  [{expr}]")
                return

            time.sleep(interval)

    def check_at(self, var_id: str, condition, at: float, tolerance: float = 0.1, interval: float = 0.05) -> None:
        """
        Assert that condition first becomes true at approximately `at` seconds.

        Fails if the transition happens before (at - tolerance),
        or if no transition is detected by (at + tolerance).
        """
        expr = self._condition_expr()
        start = time.monotonic()
        transition_time = None
        value = None
        prev = False

        while time.monotonic() - start < at + tolerance:
            elapsed = time.monotonic() - start
            value = self.cl.read(var_id, quiet=True)
            current = bool(condition(value))

            if current and not prev:
                transition_time = elapsed
                if transition_time < at - tolerance:
                    logger.error(
                        f"CHECK FAIL  {var_id} = {value}  [{expr}]"
                        f"  too early: {transition_time:.3f}s (expected {at}s ±{tolerance}s)"
                    )
                    self._record_failure(
                        f"check_at failed: {var_id} transitioned too early at {transition_time:.3f}s"
                    )
                    return
                break

            prev = current
            time.sleep(interval)

        if transition_time is None:
            logger.error(
                f"CHECK FAIL  {var_id} = {value}  [{expr}]"
                f"  no transition within {at}s ±{tolerance}s"
            )
            self._record_failure(f"check_at failed: {var_id} did not transition within expected window")
            return

        logger.info(
            f"CHECK PASS  {var_id} = {value}  [{expr}]"
            f"  transitioned at {transition_time:.3f}s (expected {at}s ±{tolerance}s)"
        )

    @staticmethod
    def _condition_expr() -> str:
        """Extract the lambda body from the caller's source line."""
        frame = inspect.stack()[2]  # 0=_condition_expr, 1=check_*, 2=test function
        if not frame.code_context:
            return "unknown"
        source = frame.code_context[0].strip()
        try:
            args = source[source.index("(") + 1 : source.rindex(")")].strip()
            if "lambda" in args:
                lambda_body = args[args.index("lambda"):]
                return lambda_body[lambda_body.index(":") + 1:].strip()
            return args
        except ValueError:
            return source
