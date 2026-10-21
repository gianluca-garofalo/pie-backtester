"""Playwright end-to-end tests: start the real app and drive it in Chromium.

They use live Yahoo Finance data, so they are skipped by a plain `pytest` run.
Run them with:  python -m pytest -m e2e
"""
import os
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
         f"--server.port={port}", "--browser.gatherUsageStats=false"],
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
        if self.page.get_by_role("combobox", name="Load example pie").input_value() != name:
            self.choose("Load example pie", name)
        self.click("Load example")

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
                cells = [c.inner_text().strip() for c in row.locator("[role=gridcell]").all()]
                if any(cells):
                    out.append(cells)
            if out:
                return out
            self.page.wait_for_timeout(250)
        return []

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

    def run_backtest(self):
        self.click("Run backtest")
        self.wait()  # a ticker fix triggers one more rerun

    def metrics(self):
        out = {}
        for m in self.page.get_by_test_id("stMetric").all():
            label = m.get_by_test_id("stMetricLabel").inner_text().strip()
            out[label] = m.get_by_test_id("stMetricValue").inner_text().strip()
        return out

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

