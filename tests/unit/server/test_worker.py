from __future__ import annotations

from typing import Any, cast

from parsehawk.server.container import Container
from parsehawk.server.worker.main import _run_next_queued


class _QueueService:
    def __init__(self, *jobs: object) -> None:
        self.jobs = list(jobs)
        self.calls = 0

    def run_next_queued(self) -> object | None:
        self.calls += 1
        return self.jobs.pop(0) if self.jobs else None


class _Container:
    def __init__(self, *, extraction: _QueueService, parsing: _QueueService) -> None:
        self.extraction_job_service = extraction
        self.parse_job_service = parsing


def test_worker_round_robins_between_non_empty_job_queues() -> None:
    extraction = _QueueService("extraction-1", "extraction-2")
    parsing = _QueueService("parse-1", "parse-2")
    container = cast(
        Container,
        cast(Any, _Container(extraction=extraction, parsing=parsing)),
    )

    first, prefer_parse = _run_next_queued(container, prefer_parse=False)
    second, prefer_parse = _run_next_queued(container, prefer_parse=prefer_parse)
    third, prefer_parse = _run_next_queued(container, prefer_parse=prefer_parse)
    fourth, _ = _run_next_queued(container, prefer_parse=prefer_parse)

    assert [first, second, third, fourth] == [
        "extraction-1",
        "parse-1",
        "extraction-2",
        "parse-2",
    ]


def test_worker_falls_back_to_non_empty_queue_and_flips_priority() -> None:
    extraction = _QueueService("extraction-1")
    parsing = _QueueService()
    container = cast(
        Container,
        cast(Any, _Container(extraction=extraction, parsing=parsing)),
    )

    job, prefer_parse = _run_next_queued(container, prefer_parse=True)

    assert job == "extraction-1"
    assert prefer_parse is True
    assert parsing.calls == 1
    assert extraction.calls == 1
