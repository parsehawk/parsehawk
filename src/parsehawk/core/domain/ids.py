from __future__ import annotations

import secrets
import threading
import time

_CROCKFORD_BASE32 = "0123456789abcdefghjkmnpqrstvwxyz"
_RANDOM_ID_BITS = 80
_RANDOM_ID_LENGTH = 26
_TIMESTAMP_BITS = 48
_MAX_RANDOM = (1 << _RANDOM_ID_BITS) - 1
_MAX_TIMESTAMP_MS = (1 << _TIMESTAMP_BITS) - 1
_last_timestamp_ms = -1
_last_random = 0
_lock = threading.Lock()


def new_id(prefix: str) -> str:
    value = _new_sortable_value()
    chars = []
    for _ in range(_RANDOM_ID_LENGTH):
        chars.append(_CROCKFORD_BASE32[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def _new_sortable_value() -> int:
    global _last_random, _last_timestamp_ms

    timestamp_ms = min(time.time_ns() // 1_000_000, _MAX_TIMESTAMP_MS)
    with _lock:
        if timestamp_ms > _last_timestamp_ms:
            _last_timestamp_ms = timestamp_ms
            _last_random = secrets.randbits(_RANDOM_ID_BITS)
        else:
            _last_random = (_last_random + 1) & _MAX_RANDOM
            if _last_random == 0:
                timestamp_ms = _last_timestamp_ms + 1
                _last_timestamp_ms = min(timestamp_ms, _MAX_TIMESTAMP_MS)
        return (_last_timestamp_ms << _RANDOM_ID_BITS) | _last_random
