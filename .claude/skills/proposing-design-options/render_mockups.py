"""Render HTML mockups to full-page PNGs.

Usage:  python render_mockups.py <folder with *.html> [--out <folder>] [--width 1440]

Every <name>.html becomes <name>.png (default: next to it). Needs Playwright:
    pip install playwright && playwright install chromium
"""
import argparse
import pathlib

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--width", type=int, default=1440)
    args = parser.parse_args()
    out = args.out or args.folder
    out.mkdir(parents=True, exist_ok=True)

    pages = sorted(args.folder.glob("*.html"))
    if not pages:
        raise SystemExit(f"No .html files in {args.folder}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": 900})
        for html in pages:
            page.goto(html.resolve().as_uri())
            page.wait_for_load_state("networkidle")  # web fonts
            png = out / f"{html.stem}.png"
            page.screenshot(path=str(png), full_page=True)
            print(png)
        browser.close()


if __name__ == "__main__":
    main()
