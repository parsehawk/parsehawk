from __future__ import annotations

from parsehawk.config import Settings
from parsehawk.server.bootstrap.seeds import RECEIPT_EXTRACTOR_SEED_KEY, seed_prebuilt_data
from parsehawk.server.container import build_container


def test_seed_prebuilt_data_is_idempotent(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "parsehawk.db",
    )

    seed_prebuilt_data(settings)
    seed_prebuilt_data(settings)

    container = build_container(settings)
    try:
        extractors = container.extractor_service.list()
    finally:
        container.close()

    prebuilt = [
        extractor for extractor in extractors if extractor.seed_key == RECEIPT_EXTRACTOR_SEED_KEY
    ]
    assert len(prebuilt) == 1
    assert prebuilt[0].is_prebuilt is True
    assert prebuilt[0].seed_version == 1
    assert prebuilt[0].schema["properties"]["receipt_id"]["x-parsehawk"] == {
        "semantic": "verbatim-string"
    }
    assert "nuextract_template" not in prebuilt[0].model_dump()
