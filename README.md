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

**Health Checks** confirm price changes and listing activity, and log the result.

Both run modes are important as they define the lifecycle for the property listings. Property Listings enter the pipeline via the **discovery mode** and exit through the **health check mode**.

### Discovery Runs

Each run proceeds through seven stages:

| Stage | Description |
|---|---|
| 1. Snapshot | Loads all `ACTIVE` listings from the DB into memory |
| 2. Scrape | Fetches listings from all four Nigerian portals |
| 3. Normalise | Converts raw strings (`"₦45M"`, `"3 Beds"`) into typed Python values |
| 4. Geocode | Attaches lat/lng coordinates via neighbourhood name lookup |
| 5. Upsert | Inserts new listings, update existing ones, emit history events |
| 6. Log | Writes one row per portal to `scrape_runs` |
| 7. Notify | Sends a Telegram summary with counts and status per portal |

The three portals scraped are: **PropertyPro.ng**, **PrivateProperty.ng**, and **NigeriaPropertyCentre.ng**

---

### Health Check Runs

Each health check goes through the following stages:

| Stage | Description |
|---|---|
| 1. Snapshot | Loads eligible `ACTIVE` listings from the DB into memory using **Adaptive Cooldown** |
| 2. Check | Checks each loaded listing with its original URL to confirm its continued existence and for any recent price changes |
| 3. Log | If changes are made or listings are found to be removed, they are stored as `PRICE_CHANGE` or as `REMOVED` events respectively with the appropriate information |
| 4. Notify | Sends a Telegram summary with the run stats and results for notification |

To optimize performance and database resource usage, the health checker uses **Adaptive Cooldown** intervals based on listing age. The next check date is calculated and persisted at active confirmation time (storing it in `next_health_check_at`), which allows PostgreSQL to query candidates efficiently using a partial B-tree index.
- `< 14 days old`: Checked every 2 days (1.9 days with buffer)
- `14-60 days old`: Checked every 7 days (6.8 days with buffer)
- `> 60 days old`: Checked every 14 days (13.8 days with buffer)

Additionally, it applies a daily queue cap (`HEALTH_CHECK_LIMIT = 1000`) to guarantee a fixed maximum execution time. To prevent queue starvation (where newer, volatile listings dominate the daily limit), candidates are prioritised using a relative **Overdue Ratio** (how late they are relative to their cohort interval) rather than a simple count of missed runs. Checks are executed in micro-batches (default: 50 candidates per batch) so progress is committed incrementally and is resilient to system sleep/power interrupts.


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
│   └──  003_add_next_health_check_at.sql    # Migration to add pre-calculated next check column
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
- A Database with the schema applied
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

## Proxying & Cloud Automation (Bypassing Bot Blocks)

Since real estate portals aggressively block cloud server IP ranges (like GitHub Actions runners), runs in the cloud must be proxied through a clean residential IP connection. 

We resolve this by tunneling the GitHub Action runner requests back to a local proxy running on your home machine using **ngrok**.

### 1. How to run the tunnel locally
On your home machine, run:
```bash
python3 start_tunnel.py
```
This script:
1. Starts a lightweight local proxy listening on port `8118`.
2. Initiates a secure `ngrok tcp 8118` tunnel.
3. Automatically queries the local ngrok API and updates the GitHub Repository Secret `PROXY_URL` using the GitHub CLI (`gh`).

### 2. Autopilot with systemd
To run this tunnel automatically in the background on your Linux system whenever your PC is on:
1. Create a user service file at `~/.config/systemd/user/scraper-tunnel.service`:
   ```ini
   [Unit]
   Description=Residential Proxy Tunnel for Property Scraper
   After=network.target

   [Service]
   ExecStart=/path/to/property-scraper/.venv/bin/python /path/to/property-scraper/start_tunnel.py
   WorkingDirectory=/path/to/property-scraper
   Restart=always
   RestartSec=10
   Environment=PATH=/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1
   
   [Install]
   WantedBy=default.target
   ```
2. Enable and start it:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable scraper-tunnel.service
   systemctl --user start scraper-tunnel.service
   ```

---

## Running

### Discovery mode

To run a full discovery cycle:
```bash
./run.sh
```

To run discovery only for specific portals (bypassing others if they are blocked or timing out):
```bash
./run.sh --portals=privateproperty,nigeriapropertycentre
```

`run.sh` handles the full lifecycle: checks `.env`, resolves the Python version, creates or rebuilds `.venv` if needed, installs dependencies, applies the schema (idempotent), and runs the pipeline. On failure it prints the last 30 lines of `scraper.log`.

You can also run the pipeline directly:
```bash
python3 -m scraper.orchestrator [--portals=list]
```

### Health Checks

```bash
./run.sh --health-check
```

With the `--health-check` flag, `run.sh` pulls listings from the database that are due for check (based on the adaptive cooldown logic) and checks them for activity. If it determines that prices have changed or that they are no longer present, a `PRICE_CHANGE` or a `REMOVED` event for each listing is appended to the `listing_history` table respectively.

**Timing Guard**: To support local scheduling (e.g. triggering hourly), health checks are protected by a timing guard. If a successful check completed less than 22 hours ago, the script exits early.

To bypass the timing guard and the cooldown schedule to check **all active listings** immediately, add the `--all` (or `--force`) flag:

```bash
./run.sh --health-check --all
```

---

## Configuration

All configuration is in `config.py`. The key constants:

| Constant | Default | Purpose |
|---|---|---|
| `REQUEST_DELAY_MIN` / `MAX` | 2 / 3s | Random delay between listing fetches |
| `MAX_RETRIES` | 3 | Retries per request (exponential backoff) |
| `RETRY_BACKOFF_BASE` | 2.0 | Backoff base in seconds (2s, 4s, 8s) |
| `REQUEST_TIMEOUT` | 15 | Timeout in seconds for HTTP requests |
| `MAX_CONSECUTIVE_FAILURES` | 5 | Max consecutive failures before early-aborting portal scrape |
| `PAGINATION_STOP_AFTER_KNOWN` | 5 | Stop paginating after N consecutive known listings |
| `SUSPECTED_SOLD_MIN_DAYS` | 30 | Minimum days active to flag a removal as a suspected sale |
| `HEALTH_CHECK_INTERVAL_DAYS` | 2 | Cooldown backup interval (in days) |
| `HEALTH_CHECK_LIMIT` | 1000 | Maximum listings checked per health-check run |
| `HEALTH_CHECK_BATCH_SIZE` | 50 | Micro-batch chunk size for HTTP scraping and DB commits |
| `HEALTH_CHECK_RUN_INTERVAL_HOURS` | 22 | Cooldown limit for the daily timing guard |
| `UPSERT_BATCH_SIZE` | 200 | DB write batch size |

`CANONICAL_NEIGHBOURHOODS` is a hardcoded list of major neighbourhood names across Lagos, Abuja, and Port Harcourt. The normaliser uses it for fuzzy address matching.


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

All tables live in the `raw_data` schema in the database.

| Table | Purpose |
|---|---|
| `raw_data.scraped_listings` | One row per listing — current state. `UNIQUE(source, external_id)`. |
| `raw_data.listing_history` | One row per event: `LISTED`, `PRICE_CHANGE`, `REMOVED`. |
| `raw_data.geocode_cache` | Persistent `(neighbourhood, city)` → `(lat, lng)` cache. |
| `raw_data.scrape_runs` | Operational log — one row per portal per run. |

Listings have a `listing_status` of `ACTIVE` or `REMOVED`. A listing is marked `suspected_sold` when it disappears after 30+ days active with at least one downward price change in its history. This is a proxy signal for transaction history — not a confirmed sale.

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

Edit `CANONICAL_NEIGHBOURHOODS` in `config.py`, adding the canonical areas as is necessary.

---

## Troubleshooting & Common Errors

### 1. Bot Detection & Proxy Failures
* **403 Forbidden / Cloud Blocking**: Real estate portals (especially `propertypro.ng` and `privateproperty.ng`) aggressively blacklist cloud provider subnets (e.g., GitHub Actions runners) and public VPNs/exit nodes, including Tor and Cloudflare WARP. If you experience persistent 403 blocks in GitHub Actions, confirm that the local `start_tunnel.py` is running and the GHA secret `PROXY_URL` is pointing to the correct active residential tunnel address (`http://*.ngrok-free.app` or similar).
* **ngrok Tunnel Connection Drops (ProxyError)**: Under environments with restrictive ISP policies or firewalls (which DNS-block or throttle TCP tunneling tools), ngrok connections can suffer from Deep Packet Inspection (DPI) or active TCP resets (RST packets) generated by the censorship gateway.
  - **Symptom**: GHA console logs output `ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))`.
  - **Remedy**: The scraper has an automated retry mechanism (`MAX_RETRIES = 3`) with exponential backoff (`RETRY_BACKOFF_BASE = 2.0`) to transparently recover from these brief sub-second drops. If the drops are extremely frequent, try changing the ngrok server region in the tunnel command (e.g. `ngrok tcp 8118 --region eu`).

### 2. Service & Logging Issues
* **Frozen or Stalled systemd Logs**: When running the tunnel under systemd, Python defaults to buffering standard output. This makes it look like `start_tunnel.py` is locked or not receiving connections.
  - **Remedy**: Ensure the systemd service file contains `Environment=PYTHONUNBUFFERED=1` in its `[Service]` block. This forces Python to flush stdout and stderr immediately, allowing you to trace traffic in real-time with `journalctl --user -u scraper-tunnel.service -f`.

### 3. Environment & Python Setup
* **`ModuleNotFoundError: No module named 'scraper'`**: Pytest or Python cannot find the root package. Make sure you run `pytest` or `python3 -m scraper.orchestrator` from the **project root directory**, not from inside the `scraper/` or `tests/` subfolders. Ensure the root `conftest.py` exists to insert the root path into `sys.path`.
* **`psycopg2-binary` Build Failures on Python 3.13**: Pre-built wheels for `psycopg2-binary` at version `2.9.9` do not support Python 3.13 and will try to compile from source, which requires Postgres header files locally. We recommend using Python 3.12 (e.g., `pyenv install 3.12.9 && pyenv local 3.12.9`), or upgrading to `psycopg2-binary==2.9.10` which contains Python 3.13 wheels.
* **Geocoder always returns `geocoded=False`**: Ensure `NOMINATIM_AGENT` in `scraper/geocoder.py` contains a valid user-agent string and contact email. Nominatim blocks empty or generic user-agents. Note that on a fresh database, the first enrichment run will take ~90 seconds to geocode 80 unique neighbourhoods due to rate limits. Subsequent runs query the geocode cache instantly.
