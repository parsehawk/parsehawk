"""Authenticated symmetric encryption for provider API keys at rest.

Provider secrets are encrypted with Fernet (AES-CBC + HMAC) before they touch
SQLite, so a leaked database file does not leak keys. The master key comes from
``PARSEHAWK_SECRET_KEY`` when set (production / shared deployments), otherwise a
``0600`` key file generated in the data directory on first run (zero-config
local use). The same source must be visible to both the API and worker
processes, which each build their own cipher.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

SECRET_KEY_ENV_VAR = "PARSEHAWK_SECRET_KEY"
KEY_FILE_NAME = ".parsehawk_secret_key"


class SecretCipher:
    """Encrypts/decrypts secret strings with a single Fernet master key."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")


def load_secret_cipher(data_dir: Path, secret_key: str | None = None) -> SecretCipher:
    """Build the cipher from the configured key or the data-dir key file."""
    return SecretCipher(_resolve_master_key(data_dir, secret_key))


def _resolve_master_key(data_dir: Path, secret_key: str | None) -> bytes:
    configured = secret_key if secret_key is not None else os.getenv(SECRET_KEY_ENV_VAR)
    if configured:
        return _derive_key(configured)
    return _key_file(data_dir)


def _derive_key(secret: str) -> bytes:
    """Turn any configured secret into a usable Fernet key.

    A value that is already a valid Fernet key is used as-is; anything else is
    folded through SHA-256 so operators can supply an arbitrary passphrase.
    """
    raw = secret.encode("utf-8")
    try:
        Fernet(raw)
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return raw


def _key_file(data_dir: Path) -> bytes:
    path = data_dir / KEY_FILE_NAME
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, Fernet.generate_key())
            finally:
                os.close(fd)
        except FileExistsError:
            # A sibling process (e.g. the worker) created it first; read below.
            pass
    return path.read_bytes()
