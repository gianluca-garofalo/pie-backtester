"""Draft operations of the pie editor: lock-aware split and scale, adding an asset."""
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


def test_with_added_gets_what_is_left():
    rows = editing.with_added([r("A", 60)], "B", "Bee")
    assert rows[-1] == {"Ticker": "B", "Name": "Bee", "Weight %": 40.0, "Lock": False}
    assert editing.with_added([r("A", 120)], "B", "Bee")[-1]["Weight %"] == 0.0


