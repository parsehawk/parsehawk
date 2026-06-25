from __future__ import annotations

import argparse
import logging
import time

from parsehawk.logging import configure_logging
from parsehawk.server.container import build_container

configure_logging("parsehawk")
logger = logging.getLogger("parsehawk.worker")


def run_once() -> bool:
    container = build_container()
    try:
        return container.job_service.run_next_queued() is not None
    finally:
        container.close()


def run_forever(poll_seconds: float) -> None:
    container = build_container()
    try:
        logger.info("Worker started")
        while True:
            job = container.job_service.run_next_queued()
            if job is None:
                time.sleep(poll_seconds)
            else:
                logger.info("Processed job %s", job.id)
    finally:
        container.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        run_forever(args.poll_seconds)


if __name__ == "__main__":
    main()
