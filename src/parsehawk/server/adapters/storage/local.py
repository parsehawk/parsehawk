from __future__ import annotations

import shutil
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pypdfium2 as pdfium

from parsehawk.core.application.ports import PreparedDocument, PreparedImage
from parsehawk.core.domain.errors import ValidationFailure
from parsehawk.core.domain.models import File


class LocalFileStorage:
    def __init__(
        self, data_dir: Path, *, pdf_max_pages: int = 25, pdf_render_dpi: int = 170
    ) -> None:
        self._data_dir = data_dir
        self._files_dir = data_dir / "files"
        self._pdf_max_pages = pdf_max_pages
        self._pdf_render_dpi = pdf_render_dpi
        self._files_dir.mkdir(parents=True, exist_ok=True)

    def write_file(self, file_id: str, file_name: str, content: bytes) -> str:
        relative_path = Path("files") / file_id / Path(file_name).name
        path = self.resolve_path(str(relative_path))
        file_dir = path.parent
        file_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(relative_path)

    def resolve_path(self, storage_path: str) -> Path:
        path = Path(storage_path)
        if path.is_absolute():
            return path
        return self._data_dir / path

    def read_text(self, file: File) -> str:
        path = self.resolve_path(file.storage_path)
        suffix = path.suffix.lower()
        if suffix == ".eml":
            return self._read_eml(path)
        if suffix in {".txt", ".md", ".csv", ".json"}:
            return path.read_text(encoding="utf-8", errors="replace")
        return path.read_bytes().decode("utf-8", errors="replace")

    def prepare_document(self, file: File) -> PreparedDocument:
        path = self.resolve_path(file.storage_path)
        storage_path = str(path)
        suffix = path.suffix.lower()
        if file.content_type.startswith("image/") or suffix in {".jpg", ".jpeg", ".png"}:
            return PreparedDocument(
                text="",
                storage_path=storage_path,
                content_type=file.content_type,
                images=[
                    PreparedImage(
                        storage_path=storage_path,
                        content_type=file.content_type,
                    )
                ],
            )
        if suffix == ".pdf" or file.content_type == "application/pdf":
            return PreparedDocument(
                text="",
                storage_path=storage_path,
                content_type="application/pdf",
                images=self._render_pdf_pages(file),
            )
        return PreparedDocument(
            text=self.read_text(file),
            storage_path=storage_path,
            content_type=file.content_type,
            images=[],
        )

    def _render_pdf_pages(self, file: File) -> list[PreparedImage]:
        pdf_path = self.resolve_path(file.storage_path)
        output_dir = pdf_path.parent / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)

        document = pdfium.PdfDocument(pdf_path)
        page_count = len(document)
        if page_count > self._pdf_max_pages:
            raise ValidationFailure(
                f"PDF has {page_count} pages; the current limit is "
                f"{self._pdf_max_pages}. Set PARSEHAWK_PDF_MAX_PAGES to raise it."
            )

        pages: list[PreparedImage] = []
        scale = self._pdf_render_dpi / 72
        try:
            for index in range(page_count):
                page_number = index + 1
                page_path = output_dir / f"page-{page_number:03d}.png"
                if not page_path.exists():
                    page = document[index]
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil().convert("RGB")
                    image.save(page_path, format="PNG")
                pages.append(
                    PreparedImage(
                        storage_path=str(page_path),
                        content_type="image/png",
                        page_number=page_number,
                    )
                )
        finally:
            document.close()
        return pages

    def delete_file(self, file: File) -> None:
        path = self.resolve_path(file.storage_path)
        if path.exists():
            shutil.rmtree(path.parent)

    @staticmethod
    def _read_eml(path: Path) -> str:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        headers = [
            f"Subject: {message.get('subject', '')}",
            f"From: {message.get('from', '')}",
            f"To: {message.get('to', '')}",
            f"Date: {message.get('date', '')}",
        ]
        bodies: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    bodies.append(str(part.get_content()))
        elif message.get_content_type() == "text/plain":
            bodies.append(str(message.get_content()))
        else:
            body = message.get_body(preferencelist=("plain", "html"))
            if body is not None:
                bodies.append(str(body.get_content()))
        return "\n".join(headers + ["", *bodies])
