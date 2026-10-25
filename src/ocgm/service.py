from __future__ import annotations

import signal
import time

from .core.config import load
from .core.monitor import Monitor


def run_service() -> int:
    cfg = load()
    monitor = Monitor(cfg)
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        while running:
            monitor.refresh()
            deadline = time.monotonic() + cfg.poll_seconds
            while running and time.monotonic() < deadline:
                time.sleep(0.5)
    finally:
        monitor.close()
    return 0
