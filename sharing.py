"""Share links.

Current links use ?p= with a short, readable value (see encode_share_link). Older links used
?pie= with zlib-compressed, base64-encoded JSON; they still open (decode_pie_from_query_param).
"""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any
from urllib.parse import quote_plus

from storage import validate_pie, normalize_pie

# ?p= value: name~currency~start~end~initial~monthly~rebalance~before_listing~TICKER:weight,...
# The name comes first and may contain anything, so it's split off from the right.
SHARE_FIELDS = 9
REBALANCE_CODES = {"Never": "N", "Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}
BEFORE_LISTING_CODES = {"wait": "w", "cash": "c"}

MAX_SHARE_URL_PARAM_LEN = 2000
MAX_DECODED_BYTES = 64_000  # far above any real pie; stops zip bombs in crafted links


def encode_pie_to_query_param(pie_data: dict[str, Any]) -> str:
    """Compress and base64-encode pie dictionary into a URL-safe string."""
    is_valid, err = validate_pie(pie_data)
    if not is_valid:
        raise ValueError(f"Invalid pie data: {err}")

    norm = normalize_pie(pie_data)
    norm.pop("id")  # keeps links short; the receiver gets a fresh id
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
        decompressor = zlib.decompressobj()
        json_bytes = decompressor.decompress(compressed, MAX_DECODED_BYTES)
        if decompressor.unconsumed_tail:
            return None
        data = json.loads(json_bytes.decode('utf-8'))
        is_valid, _ = validate_pie(data)
        if is_valid:
            return normalize_pie(data)
    except Exception:
        pass
    return None


def _num(x: float) -> str:
    return f"{float(x):g}"  # 1000.0 -> "1000", 33.33 -> "33.33"


def encode_share_link(pie_data: dict[str, Any]) -> str:
    """The ?p= value for a pie, already URL-encoded. Asset names are left out to keep it short."""
    is_valid, err = validate_pie(pie_data)
    if not is_valid:
        raise ValueError(f"Invalid pie data: {err}")
    pie = normalize_pie(pie_data)
    fields = [
        pie["name"], pie["currency"], pie.get("start") or "", pie.get("end") or "",
        _num(pie["initial"]), _num(pie["monthly"]),
        REBALANCE_CODES.get(pie["rebalance"], "N"), BEFORE_LISTING_CODES.get(pie["before_listing"], "w"),
        ",".join(f"{a['ticker']}:{_num(a['weight'])}" for a in pie["assets"]),
    ]
    return quote_plus("~".join(fields), safe="~:,-.")


def read_share_link(value: str) -> tuple[dict[str, Any] | None, str]:
    """(pie, "") from a ?p= value as the app receives it (already URL-decoded), or (None, why not).

    A pie whose weights don't add up to 100% still opens: the table's total line and Scale to 100%
    can fix it, which is friendlier than refusing the whole link.
    """
    if not value or not isinstance(value, str):
        return None, "it's empty"
    if len(value) > MAX_SHARE_URL_PARAM_LEN:
        return None, "it's too long"
    parts = value.rsplit("~", SHARE_FIELDS - 1)
    if len(parts) != SHARE_FIELDS:
        return None, "it looks cut off: some of its parts are missing"
    name, currency, start, end, initial, monthly, rebalance, before, assets = parts
    try:
        amounts = {"initial": float(initial), "monthly": float(monthly)}
    except ValueError:
        return None, "its amounts aren't numbers"
    rebalances = {v: k for k, v in REBALANCE_CODES.items()}
    if rebalance not in rebalances:
        return None, f"it has an unknown rebalance code {rebalance!r}"
    befores = {v: k for k, v in BEFORE_LISTING_CODES.items()}
    if before not in befores:
        return None, f"it has an unknown code {before!r} for assets that list later"
    try:
        holdings = [{"ticker": t, "weight": float(w)} for t, w in (a.rsplit(":", 1) for a in assets.split(","))]
    except ValueError:
        return None, "its assets aren't in the form TICKER:weight"
    data = {"name": name, "currency": currency, "start": start or None, "end": end or None, **amounts,
            "rebalance": rebalances[rebalance], "before_listing": befores[before], "assets": holdings}
    is_valid, err = validate_pie(data, whole=False)
    if not is_valid:
        return None, err[0].lower() + err[1:]
    return normalize_pie(data, whole=False), ""


def decode_share_link(value: str) -> dict[str, Any] | None:
    """A normalized pie from a ?p= value, or None (see read_share_link for the reason)."""
    return read_share_link(value)[0]
