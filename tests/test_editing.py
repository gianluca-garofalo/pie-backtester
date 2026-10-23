"""Draft operations of the pie editor: lock-aware split and scale, pasted lists, adding an asset."""
import editing


def r(ticker, weight, lock=False):
    return {"Ticker": ticker, "Name": ticker, "Weight %": weight, "Lock": lock}


def weights(rows):
    return [x["Weight %"] for x in rows]


def test_split_evenly_shares_100_and_the_last_row_takes_the_rest():
    assert weights(editing.split_evenly([r("A", 0), r("B", 0), r("C", 0)])) == [33.33, 33.33, 33.34]


def test_split_evenly_skips_locked_rows():
    assert weights(editing.split_evenly([r("A", 50, lock=True), r("B", 10), r("C", 10)])) == [50, 25, 25]


def test_scale_to_100_skips_locked_rows():
    assert weights(editing.scale_to_100([r("A", 40, lock=True), r("B", 20), r("C", 10)])) == [40, 40, 20]


def test_scale_to_100_gives_the_rounding_rest_to_the_biggest_row():
    assert weights(editing.scale_to_100([r("A", 1), r("B", 1), r("C", 1)])) == [33.34, 33.33, 33.33]


def test_scale_or_split_with_everything_locked_changes_nothing():
    rows = [r("A", 40, lock=True), r("B", 20, lock=True)]
    assert weights(editing.scale_to_100(rows)) == [40, 20]
    assert weights(editing.split_evenly(rows)) == [40, 20]


def test_scale_with_unlocked_rows_at_zero_changes_nothing():
    assert weights(editing.scale_to_100([r("A", 40, lock=True), r("B", 0)])) == [40, 0]


def test_operations_leave_the_input_alone():
    rows = [r("A", 10), r("B", 10)]
    editing.split_evenly(rows)
    editing.scale_to_100(rows)
    assert weights(rows) == [10, 10]


def test_remaining():
    assert editing.remaining([r("A", 60.004), r("B", 10)]) == 30.0
    assert editing.remaining([r("A", 70), r("B", 50)]) == -20.0


def test_parse_paste_spreadsheet_lines():
    pairs, bad = editing.parse_paste("Ticker\tWeight\nVWCE.DE\t60%\nAGGH.L;12,5\n\nIWDA.AS, 27.5\nnonsense\n")
    assert pairs == [("VWCE.DE", 60.0), ("AGGH.L", 12.5), ("IWDA.AS", 27.5)]
    assert bad == ["line 6: nonsense"]


def test_parse_paste_spaces_and_lower_case():
    pairs, bad = editing.parse_paste("vwce.de 60\n  aapl   40 % \nMSFT -5\nX 1e400")
    assert pairs == [("VWCE.DE", 60.0), ("AAPL", 40.0)]
    assert bad == ["line 3: MSFT -5", "line 4: X 1e400"]  # no negative or endless weights


def test_with_added_gets_what_is_left():
    rows = editing.with_added([r("A", 60)], "B", "Bee")
    assert rows[-1] == {"Ticker": "B", "Name": "Bee", "Weight %": 40.0, "Lock": False}
    assert editing.with_added([r("A", 120)], "B", "Bee")[-1]["Weight %"] == 0.0


def test_merge_pasted_replaces_and_reports_duplicates_and_missing():
    found = [("AAPL", "AAPL", "Apple", 30.5), ("SGLN", "SGLN.L", "Gold", 50), ("AAPL", "AAPL", "Apple", 5)]
    rows, notes = editing.merge_pasted([r("MSFT", 100)], found, ["ZZZZ9"], replace=True)
    assert [(x["Ticker"], x["Weight %"]) for x in rows] == [("AAPL", 35.5), ("SGLN.L", 50)]
    assert notes == ["AAPL is in the list twice: its weights were added up (35.50%).",
                     "Not found, so left out: ZZZZ9."]


def test_merge_pasted_adds_and_says_which_weights_changed():
    rows, notes = editing.merge_pasted([r("MSFT", 60, lock=True), r("AAPL", 40)],
                                       [("msft", "MSFT", "Microsoft", 10), ("VWCE.DE", "VWCE.DE", "All-World", 30)],
                                       [], replace=False)
    assert [(x["Ticker"], x["Weight %"], x["Lock"]) for x in rows] == \
        [("MSFT", 10, True), ("AAPL", 40, False), ("VWCE.DE", 30, False)]
    assert notes == ["MSFT was already in the pie: its weight is now 10.00%."]
