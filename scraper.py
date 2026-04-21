#!/usr/bin/env python3
"""
WhatsApp Community Members Extractor
=====================================
Connects to an EXISTING Chrome session via remote debugging so WhatsApp Web
sees a normal human browser (lower ban risk than a fresh automated browser).

HOW TO USE
----------
1. Close Chrome completely (or use a separate Chrome profile).
2. Relaunch Chrome with remote debugging enabled:

   Linux:
     google-chrome --remote-debugging-port=9222 \
       --user-data-dir=/tmp/chrome-debug-wa --no-sandbox

3. In that Chrome window, open https://web.whatsapp.com and log in.
4. Navigate to your Community -> open the Members list -> scroll it back to
   the very top.
5. Run this script:
     poetry run python scraper.py

Results are saved to whatsapp_members.csv in the current directory.
A checkpoint file (whatsapp_members_checkpoint.json) is written after every
scroll so the script can resume safely after a crash.
"""

import csv
import json
import os
import re
import sys
import time
from typing import Any, Optional

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CHROME_DEBUG_PORT: int = 9222
TOTAL_MEMBERS: int = 522
SCROLL_STEP_PX: int = 350
SCROLL_PAUSE_S: float = 1.2
MAX_NO_CHANGE: int = 8
OUTPUT_DIR: str = "output"
OUTPUT_FILE: str = f"{OUTPUT_DIR}/whatsapp_members.csv"
CHECKPOINT_FILE: str = f"{OUTPUT_DIR}/whatsapp_members_checkpoint.json"

# Phone number: starts with + or a digit, followed by >= 6 more digit/space/dash chars.
PHONE_RE: re.Pattern[str] = re.compile(r"^\+?\d[\d\s\-\(\)]{6,}$")
# ---------------------------------------------------------------------------


def connect_to_chrome(port: int) -> webdriver.Chrome:
    """Attach Selenium to an already-running Chrome instance via remote debugging."""
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print(f"[OK] Connected to Chrome on port {port}.")
        print(f"     Current page: {driver.current_url}\n")
        return driver
    except WebDriverException as exc:
        print(f"[ERROR] Could not connect to Chrome: {exc}")
        print(
            "\nMake sure Chrome is running with:\n"
            f"  google-chrome --remote-debugging-port={port}"
            " --user-data-dir=/tmp/chrome-debug-wa --no-sandbox\n"
        )
        sys.exit(1)


def find_scroll_container(driver: webdriver.Chrome) -> Optional[Any]:
    """Return the scrollable members-list DOM element, or None if not found."""
    return driver.execute_script("""
        const candidates = [
            '[data-testid="list-item-0"]',
            '[data-testid="list-item-1"]',
            '[role="listitem"]',
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (!el) continue;
            let node = el.parentElement;
            while (node && node !== document.body) {
                const st = window.getComputedStyle(node);
                const ov = (st.overflow || '') + (st.overflowY || '');
                if (
                    (ov.includes('scroll') || ov.includes('auto')) &&
                    node.scrollHeight > node.clientHeight + 10
                ) {
                    return node;
                }
                node = node.parentElement;
            }
        }
        return null;
        """)


def collect_visible_numbers(driver: webdriver.Chrome) -> set[str]:
    """Return all phone-number strings currently rendered in the members list.

    Uses a single JS call to avoid StaleElementReferenceException caused by
    WhatsApp's virtual list re-rendering DOM nodes mid-scroll.

    Two sources are scraped:
    - ``span[title]``  -- contacts with no saved name; the number IS the title.
    - ``span > span``  -- contacts with a saved name; the number is inner text.
    """
    candidates: list[str] = driver.execute_script("""
        const results = new Set();
        document.querySelectorAll('span[title]').forEach(el => {
            const t = (el.getAttribute('title') || '').trim();
            if (t) results.add(t);
        });
        document.querySelectorAll('span > span').forEach(el => {
            const t = (el.textContent || '').trim();
            if (t) results.add(t);
        });
        return Array.from(results);
        """)
    return {c for c in candidates if PHONE_RE.match(c)}


def load_checkpoint(path: str) -> set[str]:
    """Return numbers persisted in *path*, or an empty set if the file is absent."""
    try:
        with open(path, encoding="utf-8") as fh:
            data: dict[str, list[str]] = json.load(fh)
        numbers: set[str] = set(data.get("numbers", []))
        if numbers:
            print(f"[RESUME] Loaded {len(numbers)} numbers from {path}")
        return numbers
    except FileNotFoundError:
        return set()


def save_checkpoint(numbers: set[str], path: str) -> None:
    """Atomically overwrite *path* with the current set of numbers."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"numbers": sorted(numbers)}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_csv(numbers: set[str], path: str) -> None:
    """Write *numbers* to a CSV file at *path*."""
    rows = sorted(numbers)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["phone_number"])
        for number in rows:
            writer.writerow([number])
    print(f"\nSaved {len(rows)} numbers -> {path}")


def scroll_and_extract(driver: webdriver.Chrome, total: int) -> set[str]:
    """Scroll through the members list and return all extracted phone numbers."""
    all_numbers: set[str] = load_checkpoint(CHECKPOINT_FILE)

    print("Searching for the scrollable members list container ...")
    container: Optional[Any] = find_scroll_container(driver)
    if container is None:
        print(
            "[ERROR] Could not find the members list.\n"
            "        Make sure the Community -> Members dialog is open and "
            "the list is scrolled to the top."
        )
        return all_numbers

    print("Container found. Starting extraction ...\n")
    no_change_streak = 0

    while True:
        try:
            visible = collect_visible_numbers(driver)
        except WebDriverException as exc:
            print(
                f"  [WARN] DOM error ({type(exc).__name__}),"
                " retrying after pause ..."
            )
            time.sleep(2)
            container = find_scroll_container(driver)
            if container is None:
                print("  [STOP] Lost the members list container after DOM error.")
                break
            continue

        before = len(all_numbers)
        all_numbers.update(visible)
        gained = len(all_numbers) - before

        print(f"  Collected {len(all_numbers):>4}/{total}  (+{gained} this scroll)")

        if gained > 0:
            save_checkpoint(all_numbers, CHECKPOINT_FILE)

        if len(all_numbers) >= total:
            print("\n[DONE] Reached the expected member count.")
            break

        if gained == 0:
            no_change_streak += 1
            if no_change_streak >= MAX_NO_CHANGE:
                print(
                    f"\n[STOP] No new numbers after {MAX_NO_CHANGE} consecutive"
                    " scrolls. The list may have ended."
                )
                break
        else:
            no_change_streak = 0

        try:
            driver.execute_script(
                "arguments[0].scrollTop += arguments[1];",
                container,
                SCROLL_STEP_PX,
            )
        except WebDriverException:
            time.sleep(2)
            container = find_scroll_container(driver)
            if container is None:
                break

        time.sleep(SCROLL_PAUSE_S)

    return all_numbers


def main() -> None:
    print("=" * 55)
    print("  WhatsApp Community Members Extractor")
    print("=" * 55)
    print(
        "\nMake sure:\n"
        "  1. Chrome was launched with:\n"
        "     google-chrome --remote-debugging-port=9222"
        " --user-data-dir=/tmp/chrome-debug-wa --no-sandbox\n"
        "  2. WhatsApp Web is open with the Community Members list visible\n"
        "  3. The members list is scrolled to the very top\n"
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = connect_to_chrome(CHROME_DEBUG_PORT)

    try:
        numbers = scroll_and_extract(driver, TOTAL_MEMBERS)
        if numbers:
            save_csv(numbers, OUTPUT_FILE)
            save_checkpoint(numbers, CHECKPOINT_FILE)
            print(f"\nExtracted {len(numbers)} phone numbers total.")
        else:
            saved = load_checkpoint(CHECKPOINT_FILE)
            if saved:
                print(
                    f"\n[WARNING] Session returned no numbers,"
                    f" but checkpoint has {len(saved)}."
                )
                print(f"          Writing checkpoint contents to {OUTPUT_FILE}")
                save_csv(saved, OUTPUT_FILE)
            else:
                print("\n[WARNING] No numbers were extracted.")
    finally:
        print("\nYour browser was left open. Script finished.")


if __name__ == "__main__":
    main()
