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


# --- short ?p= links ---
from urllib.parse import parse_qs

from sharing import encode_share_link, decode_share_link

TECH = {"name": "Tech & Co ~ 50/50", "currency": "USD", "start": "2020-01-01", "end": None,
        "initial": 1000.0, "monthly": 100.0, "rebalance": "Quarterly", "before_listing": "cash",
        "assets": [{"ticker": "QDVE.DE", "weight": 50.0, "name": "iShares S&P 500 Information Technology"},
                   {"ticker": "BRK-B", "weight": 33.33}, {"ticker": "^GSPC", "weight": 16.67}]}


def opened(value):
    """What the app gets from st.query_params after a browser opens ...?p=<value>."""
    return parse_qs(f"p={value}")["p"][0]


def test_short_link_roundtrip_keeps_pie_and_settings():
    pie = decode_share_link(opened(encode_share_link(TECH)))
    assert pie["name"] == "Tech & Co ~ 50/50"  # any characters in the name survive
    assert [(a["ticker"], a["weight"]) for a in pie["assets"]] == [("QDVE.DE", 50.0), ("BRK-B", 33.33), ("^GSPC", 16.67)]
    assert (pie["currency"], pie["start"], pie["end"]) == ("USD", "2020-01-01", None)
    assert (pie["initial"], pie["monthly"], pie["rebalance"], pie["before_listing"]) == (1000.0, 100.0, "Quarterly", "cash")


def test_short_link_is_short_and_readable():
    value = encode_share_link({"name": "Tech Leaders", "currency": "USD", "start": "2020-01-01", "initial": 1000,
                               "monthly": 100, "assets": [{"ticker": "QDVE.DE", "weight": 50, "name": "x" * 80},
                                                          {"ticker": "AAPL", "weight": 25}, {"ticker": "MSFT", "weight": 25}]})
    assert value == "Tech+Leaders~USD~2020-01-01~~1000~100~N~w~QDVE.DE:50,AAPL:25,MSFT:25"


@pytest.mark.parametrize("bad", ["", "nonsense", "a~b~c", "N~EUR~2020-01-01~~1000~100~X~w~VWCE.DE:100",
                                 "N~EUR~2020-01-01~~lots~100~N~w~VWCE.DE:100", "N~EUR~2020-01-01~~1000~0~N~w~VWCE.DE"])
def test_broken_short_links_are_rejected(bad):
    assert decode_share_link(bad) is None
