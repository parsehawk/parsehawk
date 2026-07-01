from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from parsehawk.server.adapters.security.cipher import (
    KEY_FILE_NAME,
    SecretCipher,
    load_secret_cipher,
)


def test_cipher_round_trip() -> None:
    cipher = SecretCipher(Fernet.generate_key())

    token = cipher.encrypt("sk-secret")

    assert token != "sk-secret"
    assert cipher.decrypt(token) == "sk-secret"


def test_env_passphrase_is_deterministic_across_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARSEHAWK_SECRET_KEY", "a-shared-passphrase")

    token = load_secret_cipher(tmp_path).encrypt("value")

    # No key file is written when the environment supplies the key, and a second
    # process deriving from the same passphrase can decrypt it.
    assert not (tmp_path / KEY_FILE_NAME).exists()
    assert load_secret_cipher(tmp_path).decrypt(token) == "value"


def test_env_accepts_a_raw_fernet_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("PARSEHAWK_SECRET_KEY", key)

    token = load_secret_cipher(tmp_path).encrypt("value")

    # A value that is already a valid Fernet key is used directly.
    assert Fernet(key.encode("ascii")).decrypt(token.encode("ascii")).decode("utf-8") == "value"


def test_generates_and_reuses_a_0600_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PARSEHAWK_SECRET_KEY", raising=False)
    data_dir = tmp_path / "data"

    token = load_secret_cipher(data_dir).encrypt("value")

    key_path = data_dir / KEY_FILE_NAME
    assert key_path.exists()
    assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600
    # A later load reuses the same file rather than regenerating.
    assert load_secret_cipher(data_dir).decrypt(token) == "value"
