# WhatsApp Community Members Extractor

Extracts phone numbers from a WhatsApp Web community members list by attaching
Selenium to an **already-open** Chrome session. Because it reuses your existing
browser session (via Chrome's remote debugging protocol) rather than launching a
fresh automated browser, WhatsApp Web sees a normal human-started session —
reducing ban risk compared to headless automation.

---

## How it works

WhatsApp Web renders the members list as a **virtual scroll list** — only ~10
rows are in the DOM at any time. The scraper:

1. Attaches to your running Chrome via `--remote-debugging-port`
2. Finds the scrollable members container
3. Scrolls it in small steps, harvesting phone numbers from two DOM sources:
   - `span[title]` — contacts with **no saved name** (number is the title)
   - `span > span` text — contacts **with a saved name** (number is inner text)
4. Saves a **checkpoint** after every scroll so a crash loses at most one step
5. On completion writes a CSV with all unique numbers

---

## Requirements

- Python 3.10+
- [Poetry](https://python-poetry.org/)
- Google Chrome 144+ (the correct ChromeDriver is downloaded automatically)

---

## Setup

```bash
git clone https://github.com/d-almouiee/whatsapp-members-extractor.git
cd whatsapp-members-extractor
poetry install
```

---

## Usage

### Step 1 — Launch Chrome with remote debugging

Close any existing Chrome windows, then run:

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-debug-wa \
  --no-sandbox
```

> **WSL2 users:** the `--no-sandbox` flag is required.

### Step 2 — Log in and open the Members list

In that Chrome window:

1. Go to [web.whatsapp.com](https://web.whatsapp.com) and log in
2. Open your Community → click **Members**
3. Scroll the list back to the **very top**

### Step 3 — Run the scraper

```bash
poetry run python scraper.py
```

Numbers are saved to `output/whatsapp_members.csv`. A checkpoint is written to
`output/whatsapp_members_checkpoint.json` after every scroll so you can resume
safely after a crash by simply re-running the script.

---

## Configuration

All tunable values are constants at the top of `scraper.py`:

| Constant | Default | Description |
|---|---|---|
| `CHROME_DEBUG_PORT` | `9222` | Must match `--remote-debugging-port` |
| `TOTAL_MEMBERS` | `522` | Expected community size (stop condition) |
| `SCROLL_STEP_PX` | `350` | Pixels scrolled per step |
| `SCROLL_PAUSE_S` | `1.2` | Seconds to wait between scrolls |
| `MAX_NO_CHANGE` | `8` | Scrolls with no new numbers before stopping |
| `OUTPUT_FILE` | `whatsapp_members.csv` | CSV output path |
| `CHECKPOINT_FILE` | `whatsapp_members_checkpoint.json` | Incremental save path |

---

## Development

```bash
# Format
poetry run black scraper.py

# Lint
poetry run flake8 scraper.py

# Type-check
poetry run mypy scraper.py
```

---

## Disclaimer

This tool is for **personal use only** — specifically for community admins who
need to export their own member list. Automating WhatsApp Web may violate
WhatsApp's Terms of Service. Use responsibly.
