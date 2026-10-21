import pytest
from sharing import encode_pie_to_query_param, decode_pie_from_query_param

def test_encode_decode_roundtrip():
    pie_data = {
        "version": 1,
        "name": "Global Equity",
        "currency": "EUR",
        "assets": [
            {"ticker": "VWCE.DE", "weight": 70.0, "name": "Vanguard FTSE All-World"},
            {"ticker": "AGGH.DE", "weight": 30.0, "name": "Global Aggregate Bond"}
        ]
    }

    encoded = encode_pie_to_query_param(pie_data)
    assert isinstance(encoded, str)
    assert len(encoded) > 0

    decoded = decode_pie_from_query_param(encoded)
    assert decoded is not None
    assert decoded["name"] == "Global Equity"
    assert decoded["currency"] == "EUR"
    assert len(decoded["assets"]) == 2
    assert decoded["assets"][0]["ticker"] == "VWCE.DE"

def test_decode_invalid():
    assert decode_pie_from_query_param("invalid_base64_data!!!") is None
    assert decode_pie_from_query_param("") is None


def test_decode_rejects_oversized_payload():
    import base64, json, zlib
    huge = {"assets": [{"ticker": "VWCE.DE", "weight": 100.0, "name": "x" * 5_000_000}]}
    param = base64.urlsafe_b64encode(zlib.compress(json.dumps(huge).encode(), 9)).decode().rstrip("=")
    assert decode_pie_from_query_param(param) is None
