# UI End-to-End Test — Support Copilot Dashboard

Playwright-based UI test for the Streamlit dashboard at
`http://13.211.160.77:8501/`.

Script: `tests/e2e/test_dashboard_ui.py`

## Prerequisites

```bash
uv sync
uv add --dev playwright        # if not already installed
uv run playwright install chromium
```

The target deployment must be reachable and the API must have valid
`GROQ_API_KEY` / `GOOGLE_API_KEY` configured (otherwise draft generation
and memory search return 503).

## Test Steps Covered

1. Open the dashboard and wait for it to load.
2. Click **Ingest Knowledge Base** (sidebar) and assert `Indexed N files / M chunks`.
3. Create a ticket with:
   - Customer Email: `amrita.ch@gmail.com`
   - Company: `Personal`
   - Customer Name: `Amrita`
   - Priority: `medium`
   - Subject: `Cheque Services not active`
   - Description: `Cheque Services not active after 5 days for Savings account opening`
   - **Auto-generate draft** unchecked
   - Click **Create Ticket** and assert `Ticket #N created`.
4. In **Select ticket**, pick the last (highest ID) ticket matching the email/subject above.
5. Click **Generate Draft** and assert `Draft generated`.
6. Click **Accept Draft** and assert `Draft accepted and memory updated`.
7. Click **Run Memory Probe** and assert a result message
   (`Found N memory hit(s).` or `No memory hits for this query yet.`).

## Running

```bash
# Headed (visible browser)
uv run python tests/e2e/test_dashboard_ui.py

# Headless (CI)
uv run python tests/e2e/test_dashboard_ui.py --headless

# Against a different deployment
uv run python tests/e2e/test_dashboard_ui.py --url http://localhost:8501/
```

## Artifacts

Saved to `tests/e2e/artifacts/` (gitignored):

- `*.webm` — full video recording of the test run
- `final_state.png` — screenshot after all steps pass
- `failure.png` — screenshot captured if any step fails

Exit code is `0` on success, `1` on failure; step progress is logged to stdout.
