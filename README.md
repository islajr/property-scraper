# 🤖 Property Scraper

![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)
![Build Status](https://github.com/islajr/property-scraper/actions/workflows/python-tests.yml/badge.svg)
![Last Commit](https://img.shields.io/github/last-commit/islajr/property-scraper)

## Introduction

**Property Scraper** is an autonomous lightweight python-based data pipeline that extracts real property listing data from public Nigerian property portals, cleans and geocodes the data, and persists them to a PostgreSQL instance on Supabase on a weekly schedule. A Telegram message is sent at the end of every run with a summary of what happened.

---

## What it does

**Property Scraper** has two run modes: **Discovery Runs** and **Health Checks**.

**Discovery runs** are all about finding new property listings and storing them in the database

**Health Checks** confirm if active listings are indeed still active, and logs the result.

Both run modes are important as they create the entire lifecycle for the project. Property Listings enter and exit the pipeline from one and through the other

### Discovery Runs

Each run proceeds through seven stages:

| Stage | Description |
|---|---|
| 1. Snapshot | Load all `ACTIVE` listings from the DB into memory |
| 2. Scrape | Fetch listings from all four Nigerian portals |
| 3. Normalise | Convert raw strings (`"₦45M"`, `"3 Beds"`) into typed Python values |
| 4. Geocode | Attach lat/lng coordinates via neighbourhood name lookup |
| 5. Upsert | Insert new listings, update existing ones, emit history events |
| 6. Log | Write one row per portal to `scrape_runs` |
| 7. Notify | Send a Telegram summary with counts and status per portal |

The three portals scraped are: **PropertyPro.ng**, **PrivateProperty.ng**, and **NigeriaPropertyCentre.ng**

---

### Health Checks

Each health check goes through the following stages:

| Stage | Description |
|---|---|
| 1. Snapshot | Load all `ACTIVE` listings from the DB into memory |
| 2. Check | Checks each loaded listing with its original URL to confirm if it still exists |
| 3. Log | If changes are made or listings are found to be removed, they are stored in as `REMOVED` events with the appropriate information |
| 4. Notify | Send a Telegram summary with the run stats and results for notification |

---

## Project structure

```
property-scraper/
├── config.py                   # All configuration — env vars, constants
├── conftest.py                 # Root pytest path fix
├── pytest.ini                  # pytest settings
├── run.sh                      # Local weekly run script
├── .env                        # Local credentials (never commit)
│
├── scraper/
│   ├── models.py               # RawListing and NormalisedListing dataclasses
│   ├── orchestrator.py         # Main entry point — wires all stages together
│   ├── normaliser.py           # String → typed value conversion
│   ├── geocoder.py             # Neighbourhood → lat/lng (Nominatim + cache)
│   ├── db_writer.py            # All database reads and writes
│   ├── notifier.py             # Telegram notification
│   ├── health_checker.py       # Health Check logic
│   └── parsers/
│       ├── base_parser.py      # Shared HTTP + pagination infrastructure
│       ├── propertypro.py
│       ├── privateproperty.py
│       └── nigeriapropertycentre.py
│
├── schema/
│   ├──  001_raw_data_schema.sql # DB tables and indexes — run once
│   ├──  002_add_health_check_at.sql    # Migration to track health checks
│
└── tests/
    ├── conftest.py
    ├── fixtures/               # Saved HTML from each portal
    ├── test_parsers.py
    ├── test_normaliser.py
    ├── test_geocoder.py
    ├── test_db_writer.py
    └── test_pipeline.py
```

---

## Requirements

- Python 3.10–3.12 (3.13 is not supported — `psycopg2-binary` has no wheel for it yet)
- A Supabase project with the schema applied
- Optional: a Telegram bot token and chat ID for run notifications

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd property-scraper
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# playwright install chromium
```

**2. Create a `.env` file in the project root**

```
DATABASE_URL=postgresql://postgres.[project-id]:[password]@...
TELEGRAM_BOT_TOKEN=1234567890:ABCDEF...   # optional
TELEGRAM_CHAT_ID=123456789                # optional
```

**3. Apply the database schema**

```bash
psql $DATABASE_URL -f schema/001_raw_data_schema.sql
```

**4. Update the Nominatim user-agent**

Open `scraper/geocoder.py` and set `NOMINATIM_AGENT` to a real application name and contact email. Nominatim blocks generic or empty user-agents.

---

## Running

### Discovery mode

```bash
./run.sh
```

`run.sh` handles the full lifecycle: checks `.env`, resolves the Python version, creates or rebuilds `.venv` if needed, installs dependencies, applies the schema (idempotent), and runs the pipeline. On failure it prints the last 30 lines of `scraper.log`.

You can also run the pipeline directly:

```bash
python3 -m scraper.orchestrator
```

### Health Checks

```bash
./run.sh --health-check
```

with the `--health-check` flag, `run.sh` pulls all active listings from the database and checks them for activity. If it determines that they are no longer  present, a `REMOVED` event for each listing is appended to the `listing_history` table.

---

## Configuration

All configuration is in `config.py`. The key constants:

| Constant | Default | Purpose |
|---|---|---|
| `REQUEST_DELAY_MIN` / `MAX` | 2.0 / 5.0s | Random delay between listing fetches |
| `MAX_RETRIES` | 3 | Retries per request (exponential backoff) |
| `RETRY_BACKOFF_BASE` | 2.0 | Backoff base in seconds (2s, 4s, 8s) |
| `PAGINATION_STOP_AFTER_KNOWN` | 5 | Stop paginating after 5 consecutive known listings |
| `MISSED_RUN_REMOVAL_THRESHOLD` | 3 | Runs absent before a listing is marked `REMOVED` |
| `SUSPECTED_SOLD_MIN_DAYS` | 30 | Minimum days active to flag a removal as a suspected sale |
| `UPSERT_BATCH_SIZE` | 500 | DB write batch size |

`CANONICAL_NEIGHBOURHOODS` is a hardcoded list of ~100 neighbourhood names across Lagos, Abuja, and Port Harcourt. The normaliser uses it for fuzzy address matching.

---

## Data model

There are exactly two data objects. Everything flows through them.

**`RawListing`** — produced by a parser. Every field is a string or `None`. No interpretation, no typing. A direct mirror of what was in the HTML.

**`NormalisedListing`** — produced by the normaliser from a `RawListing`. Every field is typed and ready for the database.

Key normalisation rules:

- All prices are stored as **kobo** (integer). ₦45,000,000 = `4_500_000_000`. Never floats, never naira.
- All floor areas are stored in **square metres**. Sqft inputs are converted automatically.
- `price_parse_failed = True` when a price string exists but cannot be interpreted.

---

## Database schema

All tables live in the `raw_data` schema on Supabase.

| Table | Purpose |
|---|---|
| `raw_data.scraped_listings` | One row per listing — current state. `UNIQUE(source, external_id)`. |
| `raw_data.listing_history` | One row per event: `LISTED`, `PRICE_CHANGE`, `REMOVED`. |
| `raw_data.geocode_cache` | Persistent `(neighbourhood, city)` → `(lat, lng)` cache. |
| `raw_data.scrape_runs` | Operational log — one row per portal per run. |

Listings have a `listing_status` of `ACTIVE` or `REMOVED`. A listing is marked `suspected_sold` when it disappears after 30+ days active with at least one downward price change in its history. This is a proxy signal for AVM training — not a confirmed sale.

---

## Testing

All tests are fully offline. No live network calls, no real database connections.

```bash
pytest                                                     # all tests
pytest tests/test_normaliser.py                            # fastest — pure logic, no fixtures
pytest tests/test_parsers.py                               # parser selectors against fixture HTML
pytest tests/test_geocoder.py                              # cache and mocked Nominatim
pytest tests/test_db_writer.py                             # upsert logic and suspected_sold
pytest tests/test_pipeline.py                              # full parser → normalise → geocode chain

# Single class
pytest tests/test_parsers.py::TestPropertyProParser -v

# Single test
pytest tests/test_parsers.py::TestPropertyProParser::test_price_raw -v
```

Run pytest from the project root, not from inside `tests/`.

---

## Maintenance

### When a portal changes its HTML

This happens regularly. The symptom is 0 listings or ❌ in the Telegram notification.

1. Run `./run.sh` to confirm which portal is failing
2. Open a live listing in your browser, open DevTools → Inspector
3. Find the element wrapping the broken field
4. Update the relevant selector constant at the top of `scraper/parsers/<portal>.py`
5. Save the page source to `tests/fixtures/<portal>_listing.html`
6. Run `pytest tests/test_parsers.py::Test<Portal>Parser -v` to confirm

### Adding a new portal

1. Create `scraper/parsers/newportal.py` — subclass `BaseParser`, implement `source`, `base_url`, `search_url`, `get_listing_urls()`, `parse_listing()`, `next_page_url()`
2. Add `NewPortalParser(active_listings)` to the parsers list in `orchestrator.py`
3. Save a fixture HTML page to `tests/fixtures/newportal_listing.html`
4. Add a `TestNewPortalParser` class to `test_parsers.py`

### Updating the neighbourhood list

Edit `CANONICAL_NEIGHBOURHOODS` in `config.py`. This list is shared with the P0 synthetic data generator — update that copy too.

---

## Common errors

**Portal returns 0 listings**
Most likely cause is selector drift (portal changed its HTML). Less common causes: 403 from bot detection (run from a residential IP), Playwright timeout on Jiji (increase `SELECTOR_TIMEOUT`).

**`ModuleNotFoundError: No module named 'scraper'`**
Run pytest from the project root. Verify the root `conftest.py` exists.

**`psycopg2-binary` build failure**
You are likely on Python 3.13. Use Python 3.12 (`pyenv install 3.12.9 && pyenv local 3.12.9`), delete `.venv`, and re-run. Alternatively upgrade to `psycopg2-binary==2.9.10` which ships 3.13 wheels.

<!-- **`playwright install` fails with `libasound2` error**
Occurs on Ubuntu 24.04 (GitHub Actions). Install Chromium deps manually (`libnss3`, `libatk1.0-0t64`, etc.) then run `playwright install chromium` without `--with-deps`. -->

**Geocoder always returns `geocoded=False`**
Check that `NOMINATIM_AGENT` in `geocoder.py` contains a real application name and contact email. Also note: the first run after a fresh install makes one API call per unique neighbourhood (~90 seconds for 80 neighbourhoods). This is normal — subsequent runs hit the cache and make zero API calls.
