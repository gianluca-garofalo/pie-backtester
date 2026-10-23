"""What the pie editor does to its rows, kept out of the UI so it can be tested.

A row is {"Ticker", "Name", "Weight %", "Lock"}. Locked rows keep their weight when the others are split or
scaled. Every function returns new rows and leaves its input alone.
"""
from __future__ import annotations


def _weight(row) -> float:
    return float(row.get("Weight %") or 0)


def remaining(rows) -> float:
    """What's left to reach 100%; negative when the weights add up to more."""
    return round(100 - sum(_weight(x) for x in rows), 2)


def _split_rows(rows):
    rows = [dict(x) for x in rows]
    free = [x for x in rows if not x.get("Lock")]
    target = max(100 - sum(_weight(x) for x in rows if x.get("Lock")), 0.0)
    return rows, free, target


def split_evenly(rows) -> list[dict]:
    """The unlocked rows share what the locked ones leave of 100%; the last one takes the rounding rest."""
    rows, free, target = _split_rows(rows)
    if free:
        base = round(target / len(free), 2)
        for x in free:
            x["Weight %"] = base
        free[-1]["Weight %"] = round(target - base * (len(free) - 1), 2)
    return rows


def scale_to_100(rows) -> list[dict]:
    """The unlocked rows keep their proportions and fill what the locked ones leave of 100%; the biggest
    takes the rounding rest. Nothing changes when the unlocked rows are all at 0."""
    rows, free, target = _split_rows(rows)
    total = sum(_weight(x) for x in free)
    if free and total > 0:
        biggest = max(free, key=_weight)
        for x in free:
            x["Weight %"] = round(_weight(x) * target / total, 2)
        biggest["Weight %"] = round(biggest["Weight %"] + target - sum(x["Weight %"] for x in free), 2)
    return rows


def with_added(rows, symbol: str, name: str) -> list[dict]:
    """The rows plus a new asset that gets what's left to reach 100%, so the weights already set stay."""
    return [dict(x) for x in rows] + [{"Ticker": symbol, "Name": name, "Weight %": max(remaining(rows), 0.0),
                                       "Lock": False}]
