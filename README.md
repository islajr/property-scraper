# 🤖 Property Scraper

![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)
![Build Status](https://github.com/islajr/property-scraper/actions/workflows/python-tests.yml/badge.svg)
![Last Commit](https://img.shields.io/github/last-commit/islajr/property-scraper)

## Introduction

**Property Scraper** is an autonomous lightweight python-based data pipeline that extracts real property listing data from public Nigerian property portals, cleans and geocodes the data, and persists them to a PostgreSQL instance on Supabase on a weekly schedule. When Telegram credentials are configured, completed runs send a summary. Discovery is scheduled weekly and health checks daily through GitHub Actions.

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
| 2. Scrape | Fetches listings from the three enabled Nigerian portals |
| 3. Normalise | Converts raw strings (`"₦45M"`, `"3 Beds"`) into typed Python values |
| 4. Geocode | Attaches lat/lng coordinates via neighbourhood name lookup |
| 5. Upsert | Inserts new listings, updates existing ones, and emits history events |
| 6. Log | Writes one row per portal to `scrape_runs` |
| 7. Notify | Sends a Telegram summary with counts and status per portal |

The three enabled portals are **PropertyPro.ng**, **PrivateProperty.ng**, and **NigeriaPropertyCentre.com**. A Jiji parser exists but is disabled in the orchestrator; Playwright is not required for the enabled parsers.

---

### Health Check Runs

Each health check goes through the following stages:

| Stage | Description |
|---|---|
| 1. Snapshot | Loads `ACTIVE` listings with `missed_run_count > 0` whose next check is due or unset |
| 2. Check | Checks each loaded listing with its original URL to confirm its continued existence and for any recent price changes |
| 3. Log | If changes are made or listings are found to be removed, they are stored as `PRICE_CHANGE` or as `REMOVED` events respectively with the appropriate information |
| 4. Notify | Sends a Telegram summary with the run stats and results for notification |

To optimize performance and database resource usage, the health checker uses **Adaptive Cooldown** intervals based on listing age. The next check date is calculated and persisted at active confirmation time (storing it in `next_health_check_at`), which allows PostgreSQL to query candidates efficiently using a partial B-tree index.

- `< 14 days old`: Eligible again after 1.9 days
- `14–59 days old`: Eligible again after 6.8 days
- `≥ 60 days old`: Eligible again after 13.8 days

The normal queue is capped at `HEALTH_CHECK_LIMIT = 1000` candidates per run; request timeouts and retries still affect runtime. Candidates are ordered by elapsed time since the last check divided by their age-cohort interval. Listings with no `next_health_check_at` receive a ratio of 1.0. Checks run in batches of 50, with results committed incrementally and checkpoints saved after each batch.

Discovery increments `missed_run_count` only for listings absent from a successfully scraped portal that returned data. Feed absence alone does not mark a listing removed. Confirming a listing active resets its missed count, so it must be missed by discovery again before entering the normal health-check queue. `--all` bypasses this eligibility filter, cooldowns, the candidate cap, and the run timing guard.


---

## Project structure

```
property-scraper/
├── config.py                   # All configuration — env vars, constants
├── conftest.py                 # Root pytest path fix
├── pytest.ini                  # pytest settings
├── run.sh                      # Local discovery, health-check, and preview wrapper
├── .env                        # Local credentials (never commit)
│
├── scraper/
│   ├── models.py               # RawListing and NormalisedListing dataclasses
│   ├── orchestrator.py         # Main entry point — wires all stages together
│   ├── normaliser.py           # String → typed value conversion
│   ├── geocoder.py             # Neighbourhood → lat/lng (Nominatim + cache)
│   ├── db_writer.py            # All database reads and writes
│   ├── notifier.py             # Telegram notification
│   ├── health_checker.py       # Async URL checks with incremental DB writes
│   ├── checkpoint.py           # Local discovery / health-check resume state
│   └── parsers/
│       ├── base_parser.py      # Shared HTTP + pagination infrastructure
│       ├── propertypro.py
│       ├── privateproperty.py
│       ├── nigeriapropertycentre.py
│       └── jiji.py              # Disabled; requires Playwright if re-enabled
│
├── schema/
│   ├──  001_raw_data_schema.sql # DB tables and indexes — run once
│   ├──  002_add_health_check_at.sql    # Migration to track health checks
│   └──  003_add_next_health_check_at.sql    # Migration to add pre-calculated next check column
│
├── scripts/                   # Telemetry generation and dashboard rendering
├── templates/                 # Dashboard HTML and CSS source
├── web/                       # Generated dashboard, fonts, and theme script
├── data/                      # Telemetry snapshot and build fingerprint
├── start_tunnel.py             # Local proxy + ngrok + GitHub secret update
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

- Python 3.12 (used by CI and recommended for the pinned dependencies)
- PostgreSQL with the migrations in `schema/` applied
- A Nominatim contact email for geocoding
- Optional: a Telegram bot token and chat ID for run notifications

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone https://github.com/islajr/property-scraper.git
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
NOMINATIM_CONTACT_EMAIL=you@example.com
```

**3. Apply the database schema**

```bash
# Export DATABASE_URL in this shell first; psql does not load .env.
(
    set -e
    for migration in schema/*.sql; do
        psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
    done
)
```

**4. Update the Nominatim user-agent**

Set `NOMINATIM_CONTACT_EMAIL` in `.env`. `scraper/geocoder.py` builds the application user-agent from that value; no code edit is required. `run.sh` loads `.env` as shell syntax, so quote values that contain shell-special characters.

---

## Proxying & Cloud Automation (Bypassing Bot Blocks)

The cloud workflows accept an HTTP proxy through the `PROXY_URL` repository secret. A residential connection can help when a portal blocks requests from a cloud runner.

We resolve this by tunneling the GitHub Action runner requests back to a local proxy running on your home machine using **ngrok**.

### 1. How to run the tunnel locally
Install and configure `ngrok`, and authenticate the GitHub CLI with permission to update repository secrets (`gh auth login`). Keep the home machine online while cloud jobs use its proxy. From the repository root, run:
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

`run.sh` checks `.env`, selects Python (preferring 3.12), creates or rebuilds `.venv` if needed, installs dependencies, applies all SQL migrations in filename order, and runs the pipeline. On success it renders the dashboard; on failure it prints the last 30 lines of `scraper.log`. The wrapper also attempts a legacy Playwright browser install, but the enabled parsers do not use it.

You can also run the pipeline directly:
```bash
python3 -m scraper.orchestrator
python3 -m scraper.orchestrator --portals=privateproperty,nigeriapropertycentre
```

### Scheduling

The checked-in GitHub Actions workflows schedule discovery on Sundays at 20:00 UTC
(21:00 WAT) and health checks daily at 20:00 UTC (21:00 WAT). Both also support
manual dispatch. They invoke the orchestrator directly, so they do not render or
deploy the dashboard. The weekly workflow applies only the base schema; apply all
migrations during initial setup or upgrades.

### Health Checks

```bash
./run.sh --health-check
```

With the `--health-check` flag, `run.sh` pulls listings from the database that are due for check (based on the adaptive cooldown logic) and checks them for activity. If it determines that prices have changed or that they are no longer present, a `PRICE_CHANGE` or a `REMOVED` event for each listing is appended to the `listing_history` table respectively.

**Timing Guard**: To support local scheduling (e.g. triggering hourly), health checks are protected by a timing guard. If a successful health-check run was logged less than 22 hours ago, the script exits early.

To bypass the timing guard and the cooldown schedule to check **all active listings** immediately, add the `--all` (or `--force`) flag:

```bash
./run.sh --health-check --all
```

If a health-check checkpoint exists, it still supplies the saved candidate list.
Use `./run.sh --health-check --all --fresh` to start a new sweep of all active listings.

### State Checkpointing & Resume Failsafe

Both Discovery runs and Health Checks support automatic execution checkpointing to survive system sleep/wake cycles or unexpected crashes:

*   **How it works**: The pipeline writes its current state to a local `.scraper_checkpoint.json` file.
    *   *Discovery runs* write checkpoints at the end of each scraped page.
    *   *Health check runs* write checkpoints after each committed batch.
*   **Resume**: If the pipeline is interrupted and run again, it loads a checkpoint for the same mode if it is no more than 24 hours old, then resumes from its saved progress. Checkpoints are local files; the GitHub Actions workflows do not persist them between jobs. Discovery checkpoints retain collected listings and completed-portal progress without validating the requested portal scope, so use `--fresh` when changing `--portals`.
*   **Forcing a Fresh Run**: To ignore any active checkpoints and start completely fresh, add the `--fresh` flag:
    ```bash
    ./run.sh --fresh
    ./run.sh --health-check --all --fresh
    ```

### Resilient Network Retry Policies

The retry settings differ by component:

- **Discovery HTTP requests**: Up to 3 retries (4 attempts total) on HTTP 429, timeouts, connection errors, and interrupted responses. Delays are `2 ** retry_index` plus 0–1 seconds of jitter: roughly 1, 2, and 4 seconds. HTTP 403 stops that request without retrying.
- **Geocoder**: Up to 3 retries for transient request exceptions, with the same 1, 2, and 4 second backoff plus jitter. Each attempt also waits 1.1 seconds for pacing.
- **Health checks**: Up to 4 retries (5 attempts total) for `aiohttp.ClientError` or timeout exceptions, including HTTP errors raised by the checker. Delays start at 1 second, double per retry, add jitter, and are capped by `HEALTH_CHECK_MAX_BACKOFF_DELAY = 30`.
- **Concurrency**: Health checks allow 10 requests globally and 3 per domain, with a random 2–5 second delay before each listing check.
- **Logging**: Health-check retries log the first two retries at `DEBUG` and later retries at `WARNING`. Discovery and geocoder retries log at `WARNING`.

---

## Dashboard

The public dashboard is generated from `templates/dashboard.html.j2` and
`templates/style.css` into `web/index.html`. Edit the templates, then rebuild;
generated HTML is overwritten on the next build. Font assets live in `web/fonts/`.

To preview with the saved telemetry snapshot, without querying the database or
running the scraper:

```bash
.venv/bin/python scripts/render_dashboard.py --cached --force
python3 -m http.server 8086 --directory web
```

Open `http://localhost:8086`. For a normal build that refreshes telemetry, omit
`--cached`. Changes to the template or CSS invalidate the build cache.

The navigation and theme control follow akinmokun.com. Dark is the default;
explicit preferences use the shared `akinmokun-theme` parent-domain cookie and
local storage. `web/theme.js` runs before the page renders to avoid a theme flash.
Menlo is the first monospace choice, with system fallbacks where it is unavailable.

After a successful scraper invocation, `run.sh` renders the dashboard and attempts
Cloudflare Pages deployment when `DEPLOY_DASHBOARD=true` or
`CLOUDFLARE_API_TOKEN` is set. It explicitly deploys to the `master` production
branch of the `property-scraper` Pages project, which requires Node/npm and
Cloudflare authentication. A failed render skips deployment to avoid uploading
stale HTML.
`./run.sh --preview` renders and serves the dashboard on port 8080, but still
requires `.env` and refreshes telemetry; use the cached preview above for design work.

To publish a design update without running the scraper or querying the database:

```bash
.venv/bin/python scripts/render_dashboard.py --cached --force && \
    npx --yes wrangler pages deploy web --project-name=property-scraper --branch=master --commit-dirty=true
```

Wrangler normally infers the deployment branch from the current Git checkout.
An upload from `dev` or `dev-ui` creates a preview deployment; it does not update
`ps0.akinmokun.com`. Use `--branch=master` for production, or an explicit development
branch for a preview. This Pages project uses Direct Upload, so merging a GitHub
PR alone does not publish the dashboard.

## Configuration

All configuration is in `config.py`. The key constants:

| Constant | Default | Purpose |
|---|---|---|
| `REQUEST_DELAY_MIN` / `MAX` | 2 / 3s | Random delay between listing fetches |
| `MAX_RETRIES` | 3 | Retries per request (exponential backoff) |
| `RETRY_BACKOFF_BASE` | 2.0 | Exponential base: 1, 2, 4 seconds plus jitter for discovery retries |
| `REQUEST_TIMEOUT` | 15 | Timeout in seconds for HTTP requests |
| `MAX_CONSECUTIVE_FAILURES` | 5 | Max consecutive failures before early-aborting portal scrape |
| `PAGINATION_STOP_AFTER_KNOWN` | 10 | Stop paginating after N consecutive known listings |
| `SUSPECTED_SOLD_MIN_DAYS` | 30 | Minimum days since first observation for a suspected-sale removal |
| `MAX_PAGES_PER_FEED` | 5 | Maximum discovery pages per search feed |
| `HEALTH_CHECK_LIMIT` | 1000 | Normal health-check candidate cap; bypassed by `--all` |
| `HEALTH_CHECK_CONCURRENCY` | 10 | Maximum concurrent health-check requests |
| `HEALTH_CHECK_PER_DOMAIN_CONCURRENCY` | 3 | Maximum concurrent health-check requests per domain |
| `HEALTH_CHECK_DELAY_MIN` / `MAX` | 2 / 5s | Random delay before each listing check |
| `HEALTH_CHECK_MAX_BACKOFF_DELAY` | 30s | Upper bound on each health-check retry delay |
| `HEALTH_CHECK_BATCH_SIZE` | 50 | Micro-batch chunk size for HTTP scraping and DB commits |
| `HEALTH_CHECK_RUN_INTERVAL_HOURS` | 22 | Cooldown limit for the daily timing guard |
| `UPSERT_BATCH_SIZE` | 200 | DB write batch size |

`CANONICAL_NEIGHBOURHOODS` covers Lagos, Abuja, and areas in several other Nigerian states. The normaliser applies cleaned substring and fuzzy matching, checking longer canonical names first. This vocabulary is shared with P0 (PropertyDataGenerator); coordinate changes there as noted in `config.py`.

Constants are configured in Python; environment variables supply `DATABASE_URL`, optional Telegram credentials, and `NOMINATIM_CONTACT_EMAIL`.


---

## Data model

The discovery pipeline uses two listing dataclasses:

**`RawListing`** — produced by a parser. Every field is a string or `None`. No interpretation, no typing. A direct mirror of what was in the HTML.

**`NormalisedListing`** — produced by the normaliser from a `RawListing`. Every field is typed and ready for the database.

Key normalisation rules:

- Normalised prices are stored as **kobo** (integer). ₦45,000,000 = `4_500_000_000`; plain numeric portal prices are interpreted as naira before conversion.
- All floor areas are stored in **square metres**. Sqft inputs are converted automatically.
- `price_parse_failed = True` when a price is missing, blank, invalid, or explicitly non-NGN.

---

## Rental prices and billing periods

`FOR_RENT` and `FOR_SHORT_LET` describe the purpose of a listing, not its price
cadence. `price_kobo` retains the advertised NGN amount: a monthly quote is never
silently converted to a yearly amount. Explicit foreign-currency quotes retain
their raw text and currency marker but are not written as NGN kobo.

| Field | Meaning |
| --- | --- |
| `price_period` | `HOUR`, `DAY`, `NIGHT`, `WEEK`, `MONTH`, or `YEAR`; otherwise NULL |
| `price_period_count` | Number of periods covered by the amount; e.g. 6 for a six-month quote |
| `price_period_status` | `KNOWN`, `UNKNOWN`, `CONFLICT`, `UNSUPPORTED`, or `NOT_APPLICABLE` |
| `price_period_source` | Where the evidence came from: primary portal price, URL, title, description, manual, or legacy unknown |
| `raw_price_text` | Bounded primary price label, including adjacent billing-unit labels |
| `price_period_evidence` | Exact supporting text; offline recovery does not invent an original price label |
| `price_currency` / `price_basis` | Currency evidence and property/area/room/person basis; unknown values remain explicit |
| `pricing_observed_at` | Time a quote was observed; offline recovery leaves historical observation dates unchanged |

For example, NGN 300,000/month is `30000000` kobo with `MONTH`, count `1`.
NGN 1,800,000 for six months is `180000000` kobo with `MONTH`, count `6` when
the portal explicitly states the six-month total. Annual rent payable two years
upfront remains an annual quote. A nightly price with a minimum stay remains
nightly. `DAY` and `NIGHT` stay distinct.

Missing units remain `UNKNOWN`; short-let prices are not assumed daily, and rent
prices are not assumed annual. Sale prices are `NOT_APPLICABLE`. Original legacy
currencies are not certified just because the old amount is stored in `price_kobo`.
A rejected price observation preserves the previous valid quote and is recorded
as `PRICING_OBSERVATION_REJECTED`. Activity checks can still confirm the URL active.

History stores `old_pricing`, `new_pricing`, and `price_comparable` alongside the
legacy integer values. Cadence/type/basis changes or unknown units produce
`PRICING_CONTEXT_CHANGE`, rather than a comparable `PRICE_CHANGE`. Only comparable
reductions support new suspected-sale decisions. Existing history and old
suspected-sale flags are retained; legacy history has no verified unit context.
Discovery and health-check notifications report observed rental-period quality.

### Migrating and recovering existing listings

Apply **all** SQL files in filename order before running the pricing-aware writer.
Migration `004_rental_pricing.sql` adds fields, constraints, audit storage, and a
comparable-price view; `005_rental_price_summaries.sql` adds grouped summaries and
coverage. Existing rental units start unknown, sale cadence is not applicable,
and existing amounts, lifecycle dates, and historical events remain unchanged.
The local wrapper and both scheduled scraper workflows apply all migrations.

The recovery tool defaults to a read-only inventory and never writes without
`--apply`:

```bash
.venv/bin/python scripts/backfill_rental_pricing.py --mode inventory
.venv/bin/python scripts/backfill_rental_pricing.py --mode offline --limit 200 --report /tmp/rental-preview.json
```

Offline recovery requires an explicit quote matching the saved amount. General
mentions of annual fees, security, or a minimum stay are not evidence of cadence.
URL/title evidence can correct a short-let classification without guessing a unit.
After reviewing a preview, apply a bounded batch explicitly:

```bash
.venv/bin/python scripts/backfill_rental_pricing.py --mode offline --apply --limit 200 --report /tmp/rental-applied.json
```

`--source`, `--status`, `--limit` (maximum 1,000), and `--batch-size` bound each run.
Continue with `--after-id` set to the report's `last_completed_id`. Reports are
updated atomically as progress completes; writes commit per listing with an audit
run ID. Concurrently changed rows are skipped and can be revisited separately.
Reapplying unchanged offline evidence does not create duplicate repairs.

Optional live recovery revisits unresolved **active** listings at the configured
portal pacing. It is separate from the health-check queue and does not mark rows
removed or reset lifecycle dates. A successful visit records today's quote and
its history, rather than claiming to recover the original historical quote.
A live dry run still makes HTTP requests; omit `--apply` to preview without writes.

```bash
.venv/bin/python scripts/backfill_rental_pricing.py --mode live --source propertypro --limit 50 --report /tmp/rental-live-preview.json
```

After reviewing the preview, repeat the bounded live command with `--apply` if
those new observations should be persisted. Blocks, failed parsing, and redirects
to another listing remain unresolved. Removed listings are not live-refetched.
Some historical units will remain unknown permanently.

To review reversal eligibility, use `--rollback-run` with the UUID in the report;
add `--apply` to reverse eligible repairs. Later-modified listings are skipped.
The reversal is audited and preserves historical events; reverted live price
changes lose their comparable-reduction eligibility.

### Resumable live rental recovery

Use the `run` command for recovery across multiple batches. It remembers each
listing in a local SQLite queue, runs at most one worker per portal, and previews
by default. It does not run the saved-description offline heuristics. Candidates
are active `FOR_RENT`/`FOR_SHORT_LET` listings whose billing period is unresolved.

From the project directory, first import any **detailed live preview** reports
from an earlier pilot. This records the exact attempted IDs so they are not
visited again automatically. Aggregate reports cannot identify those IDs safely
and are rejected. Importing does not apply the old proposals.

```bash
.venv/bin/python scripts/backfill_rental_pricing.py import-report /absolute/path/to/pilot-reports
.venv/bin/python scripts/backfill_rental_pricing.py run --max-listings 300 --max-http-requests 1000 --max-seconds 3600
.venv/bin/python scripts/backfill_rental_pricing.py status --review-report /tmp/rental-review.json
```

Inspect the preview before allowing database updates:

```bash
.venv/bin/python scripts/backfill_rental_pricing.py run --apply --max-listings 300 --max-http-requests 1000 --max-seconds 3600
```

`run --apply` consumes saved, approved previews first, then may visit additional
pending listings within its budgets. It reuses previews without another portal
request when they are less than 24 hours old and the database row has not changed.
Changed rows are skipped; expired previews are deferred for a fresh visit.
Only explicit primary NGN quotes with supported billing periods and matching
rental purpose qualify. Ambiguous terms, foreign currencies, missing units, and
changed purposes are held for review. The worker never guesses a billing period.
Current quote amounts can change during live recovery; each applied quote uses
the existing transactional audit and history mechanism and leaves lifecycle dates
alone. An interrupted database commit is reconciled against that audit on restart.

Repeat the same command to resume. `--until-exhausted` removes only the listing
count cap; HTTP and time limits still apply. A successful exit can mean the budget
was reached or remaining jobs are deferred/held, rather than complete coverage.
Transient failures have a retry delay (30 minutes by default) and a maximum of
two visits per listing. Five consecutive systemic failures pause that portal for
30 minutes while other portals continue. Holds are not automatically revisited.
To reconsider selected IDs explicitly:

```bash
.venv/bin/python scripts/backfill_rental_pricing.py retry 123 456
```

All commands use `~/.local/state/property-scraper/rental-recovery` by default
(or `$XDG_STATE_HOME/property-scraper/rental-recovery`). `--state-dir /absolute/path`
selects a different queue; use the same path for import, run, status, and retry.
The directory contains `queue.sqlite3`, `run-<UUID>.json` progress summaries, and
`run-<UUID>.jsonl` event journals. Status reads local state without contacting
PostgreSQL or the portals, including while a runner is active. Keep this state
between runs; deleting it loses attempt history. Back it up while the worker is
stopped, including SQLite sidecar files if present. The queue is tied to its
PostgreSQL target and rejects accidental reuse against another database.

Ctrl-C or SIGTERM stops new work and preserves progress. Time limits also stop
new requests; an in-flight request can finish after the deadline. Redirects and
failed sends consume the HTTP budget; reservations are saved before sending, so a
crash can conservatively count a request that was never sent. Each request has a
15-second timeout and redirects are bounded. Recovery uses queued retries rather
than the discovery parser's long blocking backoff.

Updated health checks take priority over recovery **on the same host**. A current
visit finishes before health traffic begins; recovery waits before starting the
next visit. Both processes must use the updated code and the same OS user or a
shared `PROPERTY_SCRAPER_LOCK_DIR`. This does not coordinate jobs on other hosts
or GitHub Actions. A second local recovery runner is rejected even when it uses
a different queue directory. These commands do not install or enable a timer.

### Local rental recovery schedule

The optional user-systemd timer runs at 15 minutes past each hour, with up to two
minutes of jitter. Each invocation resumes the same queue and adds newly ingested
active rentals with unresolved billing periods. Defaults are 300 queue items,
1,000 HTTP attempts, and 30 minutes per invocation. Health checks retain priority.
The timer provides repeated invocations; individual recovery runs do not wait
indefinitely for future retries. Held listings remain a separate review task.

After pulling the merged code into your production checkout, install the units:

```bash
.venv/bin/python scripts/install_recovery_timer.py
systemctl --user daemon-reload
```

Installation does not start or enable recovery. It creates
`~/.config/systemd/user/scraper-rental-recovery.service` and `.timer`, plus
`~/.config/property-scraper/rental-recovery.env`. The environment file defaults to
`RENTAL_RECOVERY_MODE=preview`: portals are visited, but property records are not
updated. To permit automatic updates for clear price and billing-period evidence,
change that setting to `RENTAL_RECOVERY_MODE=apply` after reviewing the first batch.
Existing mode/limit settings are preserved when reinstalling. Each invocation
reads the file again; mode changes affect the next run, not an active one.

Import earlier pilot attempts before enabling the timer, as described above.
Then enable the schedule:

```bash
systemctl --user enable --now scraper-rental-recovery.timer
systemctl --user list-timers scraper-rental-recovery.timer
```

Monitor and control it with:

```bash
systemctl --user status scraper-rental-recovery.service
journalctl --user -u scraper-rental-recovery.service -n 50 --no-pager
systemctl --user start scraper-rental-recovery.service  # optional immediate run
systemctl --user disable --now scraper-rental-recovery.timer  # stop future triggers
systemctl --user stop scraper-rental-recovery.service  # stop an active run too
```

Disabling the timer does not stop an active service. Runs continue writing the
same queue and reports under `~/.local/state/property-scraper/rental-recovery`.
The lightweight entry point uses the existing `.venv` and `.env`; it does not run
discovery, install dependencies, or rebuild/deploy the dashboard. New database
prices are visible to subsequent consumers; a previously rendered static dashboard
still needs its normal rebuild. An already running manual recovery prevents a
second runner; a later timer invocation tries again.

This schedule runs while the machine and user service manager are running.
`Persistent=true` triggers one catch-up invocation after a missed schedule; it
does not wake a powered-off machine or replay every missed hour. Check
`loginctl show-user "$USER" -p Linger` if it must run while logged out; enabling
lingering is a separate host administration choice. No health or discovery timer
is modified by this installer. Existing holds are not reset when Sunday discovery
runs: new unresolved listing IDs enter the queue, while known periods need no
recovery and existing uncertain cases still require review.

### Comparing rental prices

Use `raw_data.comparable_rental_prices` for explicit NGN whole-property quotes.
`raw_data.rental_price_summary` groups active comparable quotes by city,
neighbourhood, listing type, period, and period count. `raw_data.rental_pricing_coverage`
includes unresolved rentals by source/type/status so missing evidence stays visible.
These are current-data views, not reconstructed historical series.

```sql
SELECT * FROM raw_data.rental_price_summary
WHERE price_type = 'FOR_RENT' AND price_period = 'MONTH'
  AND price_period_count = 1;

SELECT * FROM raw_data.rental_pricing_coverage;
```

The old `rebuild_snapshots.py` command now refuses writes because its external
`market.neighbourhood_snapshots` contract cannot distinguish listing purposes or
billing periods. Existing snapshots are untouched. Consumers must adopt a
versioned type/period-aware historical contract before rebuilding that series;
do not mix its legacy prices with the new comparable rental views.

---

## Database schema

All tables live in the `raw_data` schema in the database.

| Table | Purpose |
|---|---|
| `raw_data.scraped_listings` | One row per listing — current state. `UNIQUE(source, external_id)`. |
| `raw_data.listing_history` | Listing lifecycle and pricing events, including quote context and comparison eligibility. |
| `raw_data.geocode_cache` | Persistent `(neighbourhood, city)` → `(lat, lng)` cache. |
| `raw_data.scrape_runs` | Operational log — one row per portal for discovery, or a `health_check` row for a health-check run. |

Listings have a `listing_status` of `ACTIVE` or `REMOVED`. A listing is marked `suspected_sold` when a health check confirms removal after at least 30 days since first observation, with at least one downward price change in its history. This is a proxy signal for transaction history — not a confirmed sale.

---

## Testing

Parser tests use saved HTML, and the shared test fixture disables network requests during parser construction. Database/geocoder dependencies are mocked in unit tests. Real PostgreSQL pricing integration tests run only when `TEST_DATABASE_URL` explicitly selects a disposable database; they never use `DATABASE_URL`. CI starts an isolated PostgreSQL service for these tests. `config.py` still requires `DATABASE_URL` at import time; use the local `.env` or a dummy value for mocked tests.

```bash
pytest                                                     # all tests
pytest tests/test_normaliser.py                            # fastest — pure logic, no fixtures
pytest tests/test_parsers.py                               # parser selectors against fixture HTML
pytest tests/test_geocoder.py                              # cache and mocked Nominatim
pytest tests/test_db_writer.py                             # upsert logic and suspected_sold
pytest tests/test_pipeline.py                              # full parser → normalise → geocode chain
pytest tests/test_pricing.py tests/test_rental_backfill.py   # quote units, ambiguity, conservative recovery
# Include real SQL persistence/recovery tests only against an explicitly disposable DB:
# TEST_DATABASE_URL=postgresql://localhost/property_scraper_test pytest tests/test_pricing_database.py

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
5. Replace the HTML fixture used by that parser’s tests (for PropertyPro, `tests/fixtures/propertypro_listing_page.html`)
6. Run `pytest tests/test_parsers.py::Test<Portal>Parser -v` to confirm

### Adding a new portal

1. Create `scraper/parsers/newportal.py` — subclass `BaseParser`, define `source`, `base_url`, `search_urls`, and implement `get_listing_urls()`, `parse_listing()`, `next_page_url()`
2. Add `NewPortalParser(active_listings)` to the parsers list in `orchestrator.py`
3. Import the parser in `orchestrator.py`, then save a fixture HTML page to `tests/fixtures/newportal_listing.html`
4. Add a `TestNewPortalParser` class to `test_parsers.py`

### Updating the neighbourhood list

Update the shared vocabulary in P0 (PropertyDataGenerator), then keep `CANONICAL_NEIGHBOURHOODS` in `config.py` aligned with it.

---

## Troubleshooting & Common Errors

### 1. Bot Detection & Proxy Failures
* **403 Forbidden / Cloud Blocking**: Real estate portals (especially `propertypro.ng` and `privateproperty.ng`) aggressively blacklist cloud provider subnets (e.g., GitHub Actions runners) and public VPNs/exit nodes, including Tor and Cloudflare WARP. If you experience persistent 403 blocks in GitHub Actions, confirm that the local `start_tunnel.py` is running and the GHA secret `PROXY_URL` is pointing to the correct active residential tunnel address (for example, `http://4.tcp.ngrok.io:12345`, converted from the ngrok TCP URL).
* **ngrok Tunnel Connection Drops (ProxyError)**: An interrupted tunnel, local proxy failure, or network issue can prevent a cloud runner from reaching the portals through the proxy.
  - **Symptom**: GHA console logs output `ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))`.
  - **Remedy**: The scraper has an automated retry mechanism (`MAX_RETRIES = 3`) with exponential backoff (`RETRY_BACKOFF_BASE = 2.0`) for transient connection errors. Persistent failures still require checking the local proxy, tunnel process, and network connection.

### 2. Service & Logging Issues
* **Frozen or Stalled systemd Logs**: When running the tunnel under systemd, Python defaults to buffering standard output. This makes it look like `start_tunnel.py` is locked or not receiving connections.
  - **Remedy**: Ensure the systemd service file contains `Environment=PYTHONUNBUFFERED=1` in its `[Service]` block. This forces Python to flush stdout and stderr immediately, allowing you to trace traffic in real-time with `journalctl --user -u scraper-tunnel.service -f`.

### 3. Environment & Python Setup
* **`ModuleNotFoundError: No module named 'scraper'`**: Pytest or Python cannot find the root package. Make sure you run `pytest` or `python3 -m scraper.orchestrator` from the **project root directory**, not from inside the `scraper/` or `tests/` subfolders. Ensure the root `conftest.py` exists to insert the root path into `sys.path`.
* **Dependency installation failures on another Python version**: Use Python 3.12, matching CI, before changing the dependency pins. The wrapper can select other installed interpreters, but CI only checks 3.12.
* **Geocoder returns `geocoded=False`**: Set `NOMINATIM_CONTACT_EMAIL`, confirm the listing has a neighbourhood, and inspect Nominatim errors or empty results in `scraper.log`. Each uncached lookup waits 1.1 seconds before requesting; successful results are cached in memory and PostgreSQL for later runs.

### 4. Adaptive Cooldown & Health Check Safeguards
* **Spike Storms from Transient Outages**: To prevent a single failed discovery run from triggering a massive health check candidate storm, the missed run increment logic only considers portals that successfully ran and returned data. Failed or filtered portal runs do not increment the missed count.
* **Soft-404 / Redirect Loops**: Deleted listings that redirect to generic portal search pages or different properties (whilst returning `200 OK`) are verified by checking if the listing's unique `external_id` is present in the final redirected URL. If the ID is missing, the listing is correctly flagged as removed, preventing permanent check loops.
* **Queue ordering**: Normal candidates are sorted by elapsed time since the last check divided by the current cohort interval, then by the oldest check time. This balances cohorts but does not guarantee a maximum wait when demand exceeds the 1,000-candidate cap.
