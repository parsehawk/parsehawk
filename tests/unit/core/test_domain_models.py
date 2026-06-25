import pytest
from pydantic import ValidationError

from parsehawk.core.domain import ids
from parsehawk.core.domain.ids import new_id
from parsehawk.core.domain.models import (
    Example,
    ExampleInput,
    ExampleInputKind,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    Job,
    JobResult,
    JobStatus,
    ValidationIssue,
)


def test_job_state_transitions_and_result_validity() -> None:
    job = Job(
        id="job_1",
        extractor_id="extractor_1",
        file_id="file_1",
        status=JobStatus.QUEUED,
    )

    running = job.mark_running()
    assert running.status == JobStatus.RUNNING
    assert running.started_at is not None

    valid_result = JobResult(data={"receipt_id": "2"})
    completed = running.mark_completed(valid_result)
    assert completed.status == JobStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.result is valid_result
    assert valid_result.valid is True

    invalid_result = JobResult(
        data={},
        validation_errors=[ValidationIssue(path="receipt_id", message="required")],
    )
    assert invalid_result.valid is False

    failed = running.mark_failed("boom", code="custom")
    assert failed.status == JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.message == "boom"
    assert failed.error.code == "custom"

    canceled = running.mark_canceled()
    assert canceled.status == JobStatus.CANCELED
    assert canceled.completed_at is not None


def test_new_id_uses_prefix() -> None:
    generated = new_id("file")
    assert generated.startswith("file_")
    assert len(generated) == len("file_") + 26


def test_new_id_is_sortable_within_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_700_000_000_000_000_000)
    monkeypatch.setattr(ids.secrets, "randbits", lambda bits: 123)
    monkeypatch.setattr(ids, "_last_timestamp_ms", -1)
    monkeypatch.setattr(ids, "_last_random", 0)

    first = new_id("job")
    second = new_id("job")

    assert first < second


def test_new_id_advances_timestamp_when_random_suffix_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp_ms = 1_700_000_000_000
    monkeypatch.setattr(ids.time, "time_ns", lambda: timestamp_ms * 1_000_000)
    monkeypatch.setattr(ids, "_last_timestamp_ms", timestamp_ms)
    monkeypatch.setattr(ids, "_last_random", ids._MAX_RANDOM)

    new_id("job")

    assert ids._last_timestamp_ms == timestamp_ms + 1


def test_source_metadata_defaults_and_flags() -> None:
    uploaded_file = File(
        id="file_1",
        file_name="document.md",
        content_type="text/markdown",
        size_bytes=5,
        sha256="abc",
        storage_path="/tmp/document.md",
    )
    example_file = uploaded_file.model_copy(update={"source": FileSource.EXAMPLE})
    extractor = Extractor(
        id="extractor_1",
        name="Receipt",
        instructions="Extract receipt fields.",
        schema={"type": "object"},
    )
    prebuilt = extractor.model_copy(update={"source": ExtractorSource.PREBUILT})

    assert uploaded_file.source == FileSource.USER
    assert uploaded_file.is_example is False
    assert example_file.is_example is True
    assert extractor.source == ExtractorSource.USER
    assert extractor.is_prebuilt is False
    assert extractor.model_dump()["schema"] == {"type": "object"}
    assert "schema_" not in extractor.model_dump()
    assert "nuextract_template" not in extractor.model_dump()
    assert prebuilt.is_prebuilt is True


def test_example_input_validation_and_legacy_text_migration() -> None:
    legacy = Example.model_validate({"input": "hello", "output": {"receipt_id": "2"}})
    assert legacy.input.type == ExampleInputKind.TEXT
    assert legacy.input.text == "hello"

    file_input = ExampleInput(type=ExampleInputKind.FILE, file_id="file_1")
    assert file_input.file_id == "file_1"

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.FILE)

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.TEXT, text="hello", file_id="file_1")

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.TEXT)

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.FILE, file_id="file_1", text="hello")
