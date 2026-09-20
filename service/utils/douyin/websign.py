"""WebSign (x-secsdk-web-signature) for Douyin Web, pure Python implementation."""

from __future__ import annotations

import hashlib
import time
from urllib.parse import quote, unquote

__all__ = [
    "SALT",
    "SIGNATURE_PARAM",
    "UIFID_PARAM",
    "TIMESTAMP_PARAM",
    "normalize_query",
    "sign",
]

SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"
SIGNATURE_PARAM = "x-secsdk-web-signature"
UIFID_PARAM = "uifid"
TIMESTAMP_PARAM = "timestamp"


def _query_pairs(query: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        pairs.append((unquote(name), unquote(value)))
    return pairs


def _encode_pairs(pairs: list[tuple[str, str]]) -> str:
    return "&".join(
        f"{quote(name, safe='*-._')}={quote(value, safe='*-._')}"
        for name, value in pairs
    )


def normalize_query(query: str) -> str:
    return _encode_pairs(_query_pairs(query))


def sign(
    query: str,
    uifid: str,
    *,
    timestamp: int | None = None,
) -> tuple[str, str]:
    """Append visitor timestamp and compute x-secsdk-web-signature.

    Args:
        query: Full query string to be sent, containing a_bogus.
        uifid: Visitor ID from cookies (UIFID / UIFID_TEMP).
        timestamp: Epoch seconds (current time if None).

    Returns:
        (signed_query, signature)
    """
    stamp = str(int(time.time() if timestamp is None else timestamp))
    pairs = _query_pairs(query)
    if not any(name == UIFID_PARAM for name, _ in pairs):
        pairs.append((UIFID_PARAM, uifid))
    pairs.append((TIMESTAMP_PARAM, stamp))
    hashed = _encode_pairs(pairs)
    signature = hashlib.md5(f"{uifid}_{stamp}_{SALT}_{hashed}".encode()).hexdigest()
    return f"{hashed}&{SIGNATURE_PARAM}={signature}", signature
