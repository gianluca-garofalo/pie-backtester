"""Share link encoding and decoding using zlib compression and base64 urlsafe encoding."""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any
from storage import validate_pie, normalize_pie

MAX_SHARE_URL_PARAM_LEN = 2000


def encode_pie_to_query_param(pie_data: dict[str, Any]) -> str:
    """Compress and base64-encode pie dictionary into a URL-safe string."""
    is_valid, err = validate_pie(pie_data)
    if not is_valid:
        raise ValueError(f"Invalid pie data: {err}")

    norm = normalize_pie(pie_data)
    json_bytes = json.dumps(norm, separators=(',', ':')).encode('utf-8')
    compressed = zlib.compress(json_bytes, level=9)
    encoded = base64.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')
    return encoded


def decode_pie_from_query_param(param_str: str) -> dict[str, Any] | None:
    """Decode a base64-encoded compressed query string back into a normalized pie dict."""
    if not param_str or not isinstance(param_str, str):
        return None

    try:
        # Re-add base64 padding if needed
        padding = 4 - (len(param_str) % 4)
        if padding != 4:
            param_str += '=' * padding
        compressed = base64.urlsafe_b64decode(param_str)
        json_bytes = zlib.decompress(compressed)
        data = json.loads(json_bytes.decode('utf-8'))
        is_valid, _ = validate_pie(data)
        if is_valid:
            return normalize_pie(data)
    except Exception:
        pass
    return None
