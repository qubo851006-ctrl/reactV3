import logging
import time
from contextlib import contextmanager


_LOGGER = logging.getLogger("perf")


class PerfTrace:
    def __init__(self, flow: str, user_id: int | None = None):
        self.flow = flow
        self.user_id = user_id
        self._started = time.perf_counter()

    @contextmanager
    def step(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _LOGGER.info(
                "perf.step flow=%s step=%s user=%s elapsed_ms=%s",
                self.flow,
                name,
                self.user_id if self.user_id is not None else "-",
                elapsed_ms,
            )

    def finish(self):
        elapsed_ms = int((time.perf_counter() - self._started) * 1000)
        _LOGGER.info(
            "perf.total flow=%s user=%s elapsed_ms=%s",
            self.flow,
            self.user_id if self.user_id is not None else "-",
            elapsed_ms,
        )
