"""Blueprint string codec.

A Factorio blueprint string is a version byte ("0") followed by base64 of
zlib-compressed JSON.
"""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

VERSION_BYTE = "0"


def decode(blueprint_string: str) -> dict[str, Any]:
    """Decode a blueprint (or blueprint book) string into a dict."""
    s = blueprint_string.strip()
    if not s:
        raise ValueError("empty blueprint string")
    if s[0] != VERSION_BYTE:
        raise ValueError(f"unsupported blueprint string version byte {s[0]!r}")
    raw = zlib.decompress(base64.b64decode(s[1:]))
    return json.loads(raw)


def encode(data: dict[str, Any], level: int = 9) -> str:
    """Encode a dict (``{"blueprint": ...}`` or ``{"blueprint_book": ...}``) into a string."""
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return VERSION_BYTE + base64.b64encode(zlib.compress(raw, level)).decode("ascii")


def version_to_int(major: int, minor: int, patch: int, build: int = 0) -> int:
    """Pack a Factorio version into the 64-bit integer used in blueprints."""
    return (major << 48) | (minor << 32) | (patch << 16) | build


def int_to_version(value: int) -> tuple[int, int, int, int]:
    return ((value >> 48) & 0xFFFF, (value >> 32) & 0xFFFF, (value >> 16) & 0xFFFF, value & 0xFFFF)
