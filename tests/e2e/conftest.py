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
        self.sidebar = page.get_by_test_id("stSidebar")
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

    # --- the pie strip: one chip per loaded pie ---
    def chip_key(self, name):
        for el in self.page.locator("[class*='st-key-chip_name_']").all():
            if el.inner_text().strip() == name:
                cls = next(c for c in el.get_attribute("class").split() if c.startswith("st-key-chip_name_"))
                return cls.removeprefix("st-key-chip_name_")
        return None

    def chips(self):
        return [el.inner_text().strip() for el in self.page.locator("[class*='st-key-chip_name_']").all()]

    def open_pie(self, name):
        self.page.locator(f".st-key-chip_name_{self.chip_key(name)} button").first.click()
        self.wait()

    def remove_pie(self, name):
        # the ✕ is icon-only, but its accessible name says what it does
        self.page.locator(f".st-key-chip_x_{self.chip_key(name)}").get_by_role(
            "button", name=f"Remove {name}", exact=True).click()
        self.wait()

    def save_pie(self, name):
        self.page.get_by_role("button", name="Save", exact=True).click()
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_label("Pie name").fill(name)
        dialog.get_by_label("Pie name").press("Enter")  # the button says "Update pie" if the name is taken
        self.wait()
        dialog.get_by_role("button", name=re.compile("^(Save|Update) pie$")).click()
        self.wait()

    def delete_saved(self):
        """Delete the saved pie that's picked in the sidebar, confirming in the dialog."""
        self.click("Delete", root=self.sidebar, exact=True)
        self.page.get_by_role("dialog").get_by_role("button", name="Delete").click()
        self.wait()

    def open_sidebar_section(self, title):
        section = self.sidebar.get_by_test_id("stExpander").filter(has_text=title)
        if section.locator("details").get_attribute("open") is None:
            section.locator("summary").click()
            self.page.wait_for_timeout(300)

    def set_number(self, label, value):
        self.page.get_by_role("spinbutton", name=label).fill(str(value))
        self.page.keyboard.press("Enter")
        self.wait()

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
        return self.page.get_by_test_id("stDataFrame").first

    def rows(self, grid=None):
        """Non-empty rows of a table (default: the pie editor); the accessible table fills in after a rerun."""
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

    def edit_weight(self, row, value):
        self.rows()  # the grid is interactive once its accessible table is filled
        box = self.grid.bounding_box()
        for _ in range(5):
            # canvas cell: row marker and the narrow Ticker column come first
            self.page.mouse.click(box["x"] + 140, box["y"] + 35 * (row + 1) + 17)
            self.page.wait_for_timeout(200)
            self.page.keyboard.press("Enter")  # open the cell editor; typing first would eat a key
            self.page.wait_for_timeout(400)
            if self.page.evaluate("document.activeElement.classList.contains('gdg-input')"):
                break
            self.page.keyboard.press("Escape")
        else:
            raise AssertionError("cell editor did not open")
        self.page.keyboard.press("Control+a")
        self.page.keyboard.type(str(value))
        self.page.wait_for_timeout(300)  # the number editor applies typed text with a delay
        self.page.keyboard.press("Enter")
        self.wait()

    def metrics(self):
        """Tile label -> value, e.g. {"Value now": "$22.8k", ...}."""
        out = {}
        for m in self.page.get_by_test_id("stMetric").all():
            label = m.get_by_test_id("stMetricLabel").inner_text().strip()
            out[label] = m.get_by_test_id("stMetricValue").inner_text().strip()
        return out

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
