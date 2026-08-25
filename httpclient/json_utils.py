"""Robust JSON parsing helpers shared across the project.

All WordPress REST responses from f2medi.top begin with a UTF-8 BOM
(verified live), so plain ``response.json()`` raises
``JSONDecodeError: Unexpected UTF-8 BOM``. Every JSON body in this
project must go through :func:`parse_json_bytes` / :func:`parse_json_text`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("f2m.json")


def parse_json_text(text: str) -> Optional[Any]:
    """Parse a JSON string after stripping any leading UTF-8/UTF-16 BOM.

    Returns the parsed object, or ``None`` when the payload is empty,
    whitespace-only, or not valid JSON. Never raises.
    """
    if not text:
        return None

    # utf-8-sig strips \ufeff (and utf-16 BOMs via codecs detection).
    cleaned = text.lstrip("\ufeff").strip()
    if not cleaned:
        return None

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("[F2M] Invalid JSON payload: %s", exc)
        return None


def parse_json_bytes(data: bytes) -> Optional[Any]:
    """Decode raw response bytes as UTF-8 (BOM-tolerant) and parse JSON.

    Returns ``None`` for empty or undecodable payloads. Never raises.
    """
    if not data:
        return None

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        logger.debug("[F2M] Response bytes are not valid UTF-8")
        return None

    return parse_json_text(text)


def parse_json_response(response: Any) -> Optional[Any]:
    """Parse a ``requests.Response`` body robustly (BOM, invalid, empty).

    Reads raw bytes so the exact wire format is what gets decoded;
    ``requests``' own encoding sniffing is bypassed deliberately.
    """
    try:
        return parse_json_bytes(response.content)
    except AttributeError:
        return None
