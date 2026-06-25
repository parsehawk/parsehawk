from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from parsehawk.core.domain.errors import ValidationFailure
from parsehawk.core.domain.models import File
from parsehawk.server.adapters.storage.local import LocalFileStorage


def test_prepare_document_renders_pdf_pages(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path, pdf_max_pages=5, pdf_render_dpi=72)
    storage_path = storage.write_file("file_pdf", "document.pdf", pdf_bytes())
    assert storage_path == "files/file_pdf/document.pdf"
    assert storage.resolve_path(storage_path) == tmp_path / storage_path
    file = File(
        id="file_pdf",
        file_name="document.pdf",
        content_type="application/pdf",
        size_bytes=0,
        sha256="hash",
        storage_path=storage_path,
    )

    document = storage.prepare_document(file)

    assert document.text == ""
    assert document.content_type == "application/pdf"
    assert [image.page_number for image in document.images] == [1, 2]
    assert all(image.content_type == "image/png" for image in document.images)
    assert all(Path(image.storage_path).is_file() for image in document.images)


def test_prepare_document_rejects_pdf_over_page_limit(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path, pdf_max_pages=1, pdf_render_dpi=72)
    file = File(
        id="file_pdf",
        file_name="document.pdf",
        content_type="application/pdf",
        size_bytes=0,
        sha256="hash",
        storage_path=storage.write_file("file_pdf", "document.pdf", pdf_bytes()),
    )

    with pytest.raises(ValidationFailure, match="current limit is 1"):
        storage.prepare_document(file)


def pdf_bytes() -> bytes:
    first = Image.new("RGB", (96, 96), "white")
    second = Image.new("RGB", (96, 96), "white")
    buffer = BytesIO()
    first.save(buffer, "PDF", save_all=True, append_images=[second])
    return buffer.getvalue()
