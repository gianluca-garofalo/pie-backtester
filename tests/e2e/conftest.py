"""Playwright end-to-end tests: start the real app and drive it in Chromium.

They use live Yahoo Finance data, so they are skipped by a plain `pytest` run.
Run them with:  python -m pytest -m e2e
"""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app.py"


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(item.fspath).parent == Path(__file__).parent:
            item.add_marker(pytest.mark.e2e)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    """The app running from an empty folder, so saved_pies.json and secrets don't leak in."""
    workdir = tmp_path_factory.mktemp("app")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(APP), "--server.headless=true",
         f"--server.port={port}", "--browser.gatherUsageStats=false",
         # Streamlit also reads .streamlit/secrets.toml next to app.py, which would point the
         # tests at the real Supabase project; this file doesn't exist, so there are no secrets
         f"--secrets.files={workdir / 'no-secrets.toml'}"],
        cwd=workdir, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        env={**os.environ, "HOME": str(workdir)},  # ignore ~/.streamlit/secrets.toml
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{url}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Streamlit did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


class App:
    """Small page object over the Streamlit DOM."""

    def __init__(self, page: Page, url: str):
        self.page, self.url = page, url
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))

    def open(self, query=""):
        self.page.goto(self.url + "/" + query)
        expect(self.page.get_by_role("heading", name="Pie backtester")).to_be_visible(timeout=30_000)
        self.wait()
        return self

    def wait(self, timeout=180_000):
        """Wait until the script has finished rerunning."""
        self.page.wait_for_timeout(500)
        expect(self.page.get_by_test_id("stApp")).to_have_attribute(
            "data-test-script-state", "notRunning", timeout=timeout)
        expect(self.page.get_by_test_id("stSpinner")).to_have_count(0, timeout=timeout)

    def click(self, name, root=None, **kw):
        (root or self.page).get_by_role("button", name=name, **kw).click()
        self.wait()

    def choose(self, label, option):
        box = self.page.get_by_role("combobox", name=label)
        opt = self.page.get_by_role("option", name=option, exact=True)
        for _ in range(5):  # the list sometimes doesn't open on the first click
            box.click()
            try:
                opt.wait_for(timeout=3000)
                break
            except Exception:
                self.page.keyboard.press("Escape")
        opt.click()
        self.wait()

    def load_example(self, name):
        """Load an example from the Examples menu in the header."""
        body = self.page.get_by_test_id("stPopoverBody")
        option = body.get_by_role("button", name=name, exact=True)
        if not option.count() or not option.is_visible():
            self.page.get_by_role("button", name="Examples").click()
        option.click()
        self.wait()

    # --- pie cards: one per loaded pie, side by side; "own" is the pie that's open for editing ---
    def card_keys(self):
        """Pie name -> card key ("own" or the compared pie's index), in the order on screen."""
        out = {}
        for el in self.page.locator("[class*='st-key-pie_card_']").all():
            cls = next(c for c in el.get_attribute("class").split() if c.startswith("st-key-pie_card_"))
            out[el.locator(".card-name").first.inner_text().strip()] = cls.removeprefix("st-key-pie_card_")
        return out

    def cards(self):
        return list(self.card_keys())

    def editing(self):
        """The name of the open pie."""
        return next((n for n, k in self.card_keys().items() if k == "own"), None)

    def card(self, name):
        return self.page.locator(f".st-key-pie_card_{self.card_keys()[name]}")

    def open_pie(self, name):
        """Make a pie the open one (Edit on its card), then close the editor that comes up."""
        self.open_editor(name)
        self.close_editor()

    # --- the editor: a dialog; the page changes only on Apply ---
    @property
    def editor(self):
        return self.page.get_by_test_id("stDialog").filter(has=self.page.get_by_role("textbox", name="Pie name"))

    def open_editor(self, name=None):
        """The editor on a pie (default: the open one), or on a new pie when there's none."""
        if self.editor.count() and name is None:
            return self.editor
        if name is None and not self.cards():
            self.page.get_by_role("button", name="New pie").click()
        else:
            self.card(name or self.editing()).get_by_role("button", name="Edit", exact=True).click()
        expect(self.editor).to_be_visible(timeout=60_000)
        self.wait()
        return self.editor

    def close_editor(self):
        """Close without applying, with the dialog's ✕ (Escape would first go to a selected table cell)."""
        self.page.get_by_test_id("stDialog").get_by_role("button", name="Close").click()
        expect(self.page.get_by_test_id("stDialog")).to_have_count(0)
        self.wait()

    def apply(self):
        self.editor.get_by_role("button", name="Apply").click()
        expect(self.page.get_by_test_id("stDialog")).to_have_count(0)
        self.wait()

    def search(self, query):
        box = self.open_editor().get_by_role("textbox", name="Search by name, ticker or ISIN")
        box.fill(query)
        box.press("Enter")
        self.wait()

    def search_add(self, query):
        self.search(query)
        self.editor.get_by_role("button", name="Add to pie").click()
        self.wait()

    def remove_pie(self, name):
        self.card(name).get_by_role("button", name="Remove", exact=True).click()
        self.wait()

    ROWS = {"value": "Value now", "return": "Return", "per_year": "Per year", "worst_fall": "Worst fall"}

    def results(self, name=None):
        """A pie's result rows, e.g. {"Value now": "€17k", "Return": "+135.5%", ...}; {} when it has none.
        Default: the open pie."""
        k = "own" if name is None else self.card_keys().get(name)
        card = self.page.locator(f".st-key-result_{k}")
        if not card.count():
            return {}
        return {label: card.locator(f".st-key-val_{k}_{row}").inner_text().strip()
                for row, label in self.ROWS.items() if card.locator(f".st-key-val_{k}_{row}").count()}

    def metrics(self):
        return self.results()

    def window(self, name=None):
        """The period a pie's results cover, e.g. "29 Jul 2019 – 23 Oct 2026 · 7.2 yrs"."""
        k = "own" if name is None else self.card_keys()[name]
        return self.page.locator(f".st-key-window_{k}").inner_text().strip()

    def save_pie(self, name):
        self.page.locator(".st-key-save_open button").first.click()  # the header Save; cards have their own
        dialog = self.page.get_by_test_id("stDialog")
        dialog.get_by_label("Pie name").fill(name)
        dialog.get_by_label("Pie name").press("Enter")  # the button says "Update pie" if the name is taken
        self.wait()
        dialog.get_by_role("button", name=re.compile("^(Save|Update) pie$")).click()
        self.wait()

    # --- My pies: a menu in the header with your saved pies, import and download ---
    def open_my_pies(self):
        body = self.page.get_by_test_id("stPopoverBody").filter(has=self.page.locator("input[type=file]"))
        if not (body.count() and body.is_visible()):
            self.page.get_by_role("button", name=re.compile(r"^My pies")).click()
        expect(body).to_be_visible()
        return body

    def saved_row(self, name):
        return self.open_my_pies().locator("[class*='st-key-saved_row_']").filter(
            has=self.page.get_by_role("button", name=name, exact=True))

    def open_saved(self, name):
        """Open a saved pie: picking it opens it."""
        self.saved_row(name).get_by_role("button", name=name, exact=True).click()
        self.wait()

    def edit_saved(self, name):
        self.saved_row(name).get_by_role("button", name="Edit", exact=True).click()
        dialog = self.page.get_by_test_id("stDialog")
        expect(dialog).to_be_visible()
        return dialog

    def delete_saved(self, name):
        """Delete a saved pie: at once, with Undo on the page."""
        self.saved_row(name).get_by_role("button", name="Delete", exact=True).click()
        self.wait()

    def upload(self, path):
        self.open_my_pies().locator("input[type=file]").set_input_files(path)
        self.wait()

    def download(self):
        """Download the open pie's file; returns its path."""
        with self.page.expect_download() as dl:
            self.open_my_pies().get_by_role("button", name="Download pie (.json)").click()
        return dl.value.path()

    # --- the plan: the money settings, changed in the Edit plan dialog ---
    @property
    def plan(self):
        return self.page.locator(".st-key-plan")

    def open_plan(self):
        self.plan.get_by_role("button", name="Edit plan").click()
        dialog = self.page.get_by_test_id("stDialog")
        expect(dialog).to_be_visible()
        return dialog

    def set_plan(self, currency=None, initial=None, monthly=None, rebalance=None, apply=True):
        """Change settings in the Edit plan dialog, then Apply. rebalance: Never, Month, Quarter or Year."""
        dialog = self.open_plan()
        for label, value in (("Initial", initial), ("Monthly", monthly)):
            if value is not None:
                dialog.get_by_role("spinbutton", name=label).fill(str(value))
                dialog.get_by_role("spinbutton", name=label).press("Enter")
                self.page.wait_for_timeout(400)
        if currency:
            dialog.get_by_role("combobox", name="Currency").click()
            self.page.get_by_role("option", name=currency, exact=True).click()
        if rebalance:
            dialog.get_by_role("radio", name=rebalance, exact=True).click()
        if apply:
            dialog.get_by_role("button", name="Apply").click()
            self.wait()
        return dialog

    def set_date(self, label, iso):
        y, m, d = iso.split("-")
        for part, value in (("year", y), ("month", m), ("day", d)):
            self.page.get_by_role("spinbutton", name=f"{part}, {label}").click()
            self.page.keyboard.type(value)
        # the value is sent on blur; Tab would only move to the calendar button
        self.page.get_by_role("heading", name="Pie backtester").click()
        self.wait()

    # --- pie table (a canvas grid; read through its accessible table) ---
    @property
    def grid(self):
        return self.editor.get_by_test_id("stDataFrame").first

    def rows(self, grid=None):
        """Non-empty rows of a table (default: the editor's, opening and closing it if it's closed); the
        accessible table fills in after a rerun."""
        if grid is None and not self.editor.count():
            self.open_editor()
            try:
                return self.rows()
            finally:
                self.close_editor()
        for _ in range(40):
            out = []
            for row in (grid or self.grid).locator("tbody [role=row]").all():
                cells = [c.inner_text(timeout=2000).strip() for c in row.locator("[role=gridcell]").all()]
                if any(cells):
                    out.append(cells)
            if out:
                return out
            self.page.wait_for_timeout(250)
        return []

    def eventually(self, read, expected, timeout=15_000):
        """Poll read() until it returns expected; tables update a moment after the rerun ends."""
        value = None
        for _ in range(timeout // 250):
            try:
                value = read()
            except Exception as e:  # a table cell that went away while the table was redrawn
                value = e
            if value == expected:
                return value
            self.page.wait_for_timeout(250)
        assert value == expected
        return value

    def tickers(self):
        return [r[0] for r in self.rows()]

    def edit_weight(self, row, value, apply=True):
        """Change a weight in the editor (opened if needed), then Apply unless apply=False."""
        self.open_editor()
        self.rows()  # the grid is interactive once its accessible table is filled
        self.grid.scroll_into_view_if_needed()  # the clicks below are at screen coordinates
        box = self.grid.bounding_box()
        for _ in range(5):
            # canvas cell: row marker and the narrow Ticker column come first
            # a double click opens the cell editor (Enter didn't once the hidden table had the focus);
            # typing first would eat a key
            self.page.mouse.dblclick(box["x"] + 140, box["y"] + 35 * (row + 1) + 17)
            self.page.wait_for_timeout(400)
            if self.page.evaluate("document.activeElement.classList.contains('gdg-input')"):
                break
            self.page.wait_for_timeout(500)  # not Escape: that would close the dialog
        else:
            raise AssertionError("cell editor did not open")
        self.page.keyboard.press("Control+a")
        self.page.keyboard.type(str(value))
        self.page.wait_for_timeout(300)  # the number editor applies typed text with a delay
        self.page.keyboard.press("Enter")
        self.wait()
        if apply:
            self.apply()

    @staticmethod
    def amount(text):
        """'$22.8k' or '€9,100.00' -> 22800.0 / 9100.0"""
        t = text.strip().lstrip("$€£").replace(",", "").replace("−", "-")
        return float(t[:-1]) * 1000 if t.endswith("k") else float(t.split()[0])

    def alerts(self):
        return [a.inner_text() for a in self.page.get_by_test_id("stAlert").all()]

    def assert_healthy(self):
        expect(self.page.get_by_test_id("stException")).to_have_count(0)
        assert not self.errors, self.errors


@pytest.fixture
def app(page: Page, app_url):
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.set_default_timeout(30_000)
    a = App(page, app_url).open()
    yield a
    a.assert_healthy()



@pytest.fixture
def phone(browser, playwright, app_url):
    """The app on an emulated iPhone: phone user agent, touch screen, 390 px wide."""
    context = browser.new_context(**{k: v for k, v in playwright.devices["iPhone 13"].items()
                                     if k != "default_browser_type"})
    page = context.new_page()
    page.set_default_timeout(30_000)
    a = App(page, app_url).open()
    yield a
    a.assert_healthy()
    context.close()
