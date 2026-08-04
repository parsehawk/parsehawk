from __future__ import annotations

import argparse
import logging
import time

from parsehawk import tracing
from parsehawk.core.domain.errors import PersistenceBusyError
from parsehawk.core.domain.models import ExtractionJob, ParseJob
from parsehawk.logging import configure_logging
from parsehawk.server.container import Container, build_container

configure_logging("parsehawk")
logger = logging.getLogger("parsehawk.worker")
_prefer_parse_next = False


def _run_next_queued(
    container: Container,
    *,
    prefer_parse: bool,
) -> tuple[ExtractionJob | ParseJob | None, bool]:
    """Process one job and alternate queue priority after every success."""
    queues = (
        (
            ("parse", container.parse_job_service),
            ("extraction", container.extraction_job_service),
        )
        if prefer_parse
        else (
            ("extraction", container.extraction_job_service),
            ("parse", container.parse_job_service),
        )
    )
    for queue_name, service in queues:
        job = service.run_next_queued()
        if job is not None:
            return job, queue_name == "extraction"
    return None, prefer_parse


def run_once() -> bool:
    global _prefer_parse_next
    container = build_container()
    try:
        job, _prefer_parse_next = _run_next_queued(
            container,
            prefer_parse=_prefer_parse_next,
        )
        return job is not None
    finally:
        container.close()


def run_forever(poll_seconds: float) -> None:
    container = build_container()
    try:
        logger.info("Worker started")
        prefer_parse = False
        while True:
            try:
                job, prefer_parse = _run_next_queued(
                    container,
                    prefer_parse=prefer_parse,
                )
            except PersistenceBusyError:
                logger.warning("Persistence busy; retrying after %.2f seconds", poll_seconds)
                time.sleep(poll_seconds)
                continue
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
    tracing.configure_tracing(service_name="parsehawk-worker")
    if args.once:
        run_once()
    else:
        run_forever(args.poll_seconds)


if __name__ == "__main__":
    main()
