"""Playwright end-to-end test for the Support Copilot Streamlit dashboard.

Run with:
    uv run python tests/e2e/test_dashboard_ui.py [--url http://13.211.160.77:8501/] [--headless]

The script walks the golden path:
  1. Ingest Knowledge Base
  2. Create a ticket (auto-generate draft unchecked)
  3. Select the newly created ticket
  4. Generate Draft
  5. Accept Draft
  6. Run Memory Probe

A video of the run is saved under tests/e2e/artifacts/.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

TICKET = {
    "email": "amrita.ch@gmail.com",
    "company": "Personal",
    "name": "Amrita",
    "priority": "medium",
    "subject": "Cheque Services not active",
    "description": "Cheque Services not active after 5 days for Savings account opening",
}


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def wait_for_idle(page: Page, timeout: int = 120_000) -> None:
    """Wait until Streamlit finishes rerunning (status widget disappears)."""
    page.wait_for_timeout(1_000)
    status = page.get_by_test_id("stStatusWidget")
    try:
        status.wait_for(state="detached", timeout=timeout)
    except Exception:
        pass


def select_option(page: Page, select_label: str, option_text: str) -> None:
    box = page.get_by_test_id("stSelectbox").filter(has_text=select_label).first
    box.locator("div[data-baseweb='select']").click()
    dropdown = page.get_by_test_id("stSelectboxVirtualDropdown")
    dropdown.get_by_text(option_text, exact=False).first.click()


def step_ingest_knowledge_base(page: Page) -> None:
    log("Step 1: Ingest Knowledge Base")
    page.get_by_role("button", name="Ingest Knowledge Base").click()
    expect(page.get_by_text(re.compile(r"Indexed \d+ files"))).to_be_visible(
        timeout=120_000
    )
    log("  knowledge base ingested")


def step_create_ticket(page: Page) -> None:
    log("Step 2: Create Ticket")
    page.get_by_label("Customer Email").fill(TICKET["email"])
    page.get_by_label("Company").fill(TICKET["company"])
    page.get_by_label("Customer Name").fill(TICKET["name"])
    select_option(page, "Priority", TICKET["priority"])
    page.get_by_label("Subject").fill(TICKET["subject"])
    page.get_by_label("Description").fill(TICKET["description"])

    checkbox = page.get_by_text("Auto-generate draft")
    if page.get_by_role("checkbox", name="Auto-generate draft").is_checked():
        checkbox.click()
    page.get_by_role("button", name="Create Ticket").click()
    expect(page.get_by_text(re.compile(r"Ticket #\d+ created"))).to_be_visible(
        timeout=60_000
    )
    wait_for_idle(page)
    log("  ticket created")


def step_select_last_ticket(page: Page) -> None:
    log("Step 3: Select the last created ticket")
    box = page.get_by_test_id("stSelectbox").filter(has_text="Select ticket").first
    box.locator("div[data-baseweb='select']").click()
    dropdown = page.get_by_test_id("stSelectboxVirtualDropdown")
    dropdown.wait_for(state="visible", timeout=10_000)
    options = dropdown.locator("li").all_inner_texts()

    best_id, best_text = -1, None
    for text in options:
        match = re.match(r"#(\d+)", text.strip())
        if match and TICKET["email"] in text and TICKET["subject"] in text:
            ticket_id = int(match.group(1))
            if ticket_id > best_id:
                best_id, best_text = ticket_id, text.strip()
    if best_text is None:
        raise AssertionError("Newly created ticket not found in 'Select ticket' list")

    dropdown.get_by_text(best_text, exact=True).first.click()
    wait_for_idle(page)
    expect(page.get_by_text(TICKET["description"]).first).to_be_visible(timeout=30_000)
    log(f"  selected ticket #{best_id}")


def step_generate_draft(page: Page) -> None:
    log("Step 4: Generate Draft")
    page.get_by_role("button", name="Generate Draft").click()
    expect(page.get_by_text("Draft generated")).to_be_visible(timeout=180_000)
    wait_for_idle(page)
    log("  draft generated")


def step_accept_draft(page: Page) -> None:
    log("Step 5: Accept Draft")
    page.get_by_role("button", name="Accept Draft").click()
    expect(page.get_by_text("Draft accepted and memory updated")).to_be_visible(
        timeout=180_000
    )
    wait_for_idle(page)
    log("  draft accepted")


def step_memory_probe(page: Page) -> None:
    log("Step 6: Memory Probe")
    page.get_by_role("button", name="Run Memory Probe").click()
    result = page.get_by_text(
        re.compile(r"Found \d+ memory hit|No memory hits for this query yet")
    )
    expect(result.first).to_be_visible(timeout=120_000)
    log(f"  memory probe result: {result.first.inner_text()}")


def run(url: str, headless: bool) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[] if headless else ["--window-position=0,0"],
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            record_video_dir=str(ARTIFACTS_DIR),
            record_video_size={"width": 1600, "height": 1000},
        )
        page = context.new_page()
        try:
            log(f"Opening {url}")
            page.goto(url, wait_until="load", timeout=60_000)
            expect(page.get_by_text("Support Copilot Dashboard")).to_be_visible(
                timeout=60_000
            )
            wait_for_idle(page)

            step_ingest_knowledge_base(page)
            step_create_ticket(page)
            step_select_last_ticket(page)
            step_generate_draft(page)
            step_accept_draft(page)
            step_memory_probe(page)

            page.screenshot(path=str(ARTIFACTS_DIR / "final_state.png"), full_page=True)
            log("ALL STEPS PASSED")
        except Exception:
            page.screenshot(path=str(ARTIFACTS_DIR / "failure.png"), full_page=True)
            raise
        finally:
            video = page.video
            context.close()
            browser.close()
            if video:
                log(f"Video saved to {video.path()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://13.211.160.77:8501/")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    try:
        run(args.url, args.headless)
    except Exception as exc:  # noqa: BLE001
        log(f"TEST FAILED: {exc}")
        sys.exit(1)
