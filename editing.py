"""What the pie editor does to its rows, kept out of the UI so it can be tested.

A row is {"Ticker", "Name", "Weight %", "Lock"}. Locked rows keep their weight when the others are split or
scaled. Every function returns new rows and leaves its input alone.
"""
from __future__ import annotations

import re


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


# "VWCE.DE 60", "VWCE.DE<tab>60%", "AGGH.L;12,5", "IWDA.AS, 27.5": a ticker, a separator, a weight
PASTED_LINE = re.compile(r"^([A-Za-z0-9.\-=^]+)\s*[\t;, ]\s*(\d+(?:[.,]\d+)?)\s*%?$")


def parse_paste(text: str) -> tuple[list[tuple[str, float]], list[str]]:
    """(ticker, weight) pairs from a pasted list, one per line, and the lines that couldn't be read.
    Blank lines are skipped, and so is a first line without numbers (a spreadsheet's header row)."""
    pairs, bad, first = [], [], True
    for n, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        m = PASTED_LINE.match(line)
        if m:
            pairs.append((m.group(1).upper(), float(m.group(2).replace(",", "."))))
        elif not (first and not re.search(r"\d", line)):
            bad.append(f"line {n}: {line}")
        first = False
    return pairs, bad


def with_added(rows, symbol: str, name: str) -> list[dict]:
    """The rows plus a new asset that gets what's left to reach 100%, so the weights already set stay."""
    return [dict(x) for x in rows] + [{"Ticker": symbol, "Name": name, "Weight %": max(remaining(rows), 0.0),
                                       "Lock": False}]


def merge_pasted(rows, found, missing, replace) -> tuple[list[dict], list[str]]:
    """The editor's rows after a pasted list, and notes on what happened to it.

    found: (typed ticker, symbol, name, weight) for each line that matched a listing; missing: the typed
    tickers that didn't. replace=True starts from no rows; otherwise a symbol that's already there gets the
    pasted weight (keeping its lock). A symbol listed twice gets the sum of its weights."""
    out = [] if replace else [dict(x) for x in rows]
    before = {x["Ticker"] for x in out}
    pasted, counts = {}, {}
    for _, symbol, name, weight in found:
        counts[symbol] = counts.get(symbol, 0) + 1
        if symbol in pasted:
            pasted[symbol]["Weight %"] = round(pasted[symbol]["Weight %"] + float(weight), 2)
        else:
            pasted[symbol] = {"Ticker": symbol, "Name": name, "Weight %": float(weight), "Lock": False}
    notes = []
    for symbol, row in pasted.items():
        same = next((x for x in out if x["Ticker"] == symbol), None)
        if same:
            same["Weight %"] = row["Weight %"]
        else:
            out.append(row)
        if counts[symbol] > 1:
            notes.append(f"{symbol} is in the list twice: its weights were added up ({row['Weight %']:.2f}%).")
        elif symbol in before:
            notes.append(f"{symbol} was already in the pie: its weight is now {row['Weight %']:.2f}%.")
    if missing:
        notes.append("Not found, so left out: " + ", ".join(missing) + ".")
    return out, notes
