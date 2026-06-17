# PS-0 PropertyScraper — Codebase Reference

> How every file works, what connects to what, and why.
>
> This document covers the complete scraper application: all modules, data flow, database schema, configuration, testing, and operational behaviour. Read it once and you will be able to debug, extend, or fix any part of the system.

---

## Contents

1. [What This Application Does](#1-what-this-application-does)
2. [Configuration](#2-configuration-configpy)
3. [Data Models](#3-data-models-scrapermodelspy)
4. [Parsers](#4-parsers-scraperparsers)
5. [Normaliser](#5-normaliser-scrapernormaliserpy)
6. [Geocoder](#6-geocoder-scrapergeocoderpy)
7. [Database](#7-database-scraperdb_writerpy--schema)
8. [Orchestrator](#8-orchestrator-scraperorchestatorpy)
9. [Notifier](#9-notifier-scrapernotifierpy)
10. [Tests](#10-tests-tests)
11. [Running the Scraper](#11-running-the-scraper-runsh)
12. [Full Data Flow](#12-full-data-flow--one-run)
13. [Debugging](#13-debugging--what-goes-wrong-and-where)
14. [Ongoing Maintenance](#14-ongoing-maintenance)

---
## 1. What This Application Does

PropertyScraper (PS-0) is a data pipeline with two primary run modes:

1. **Discovery Runs (Weekly)**: Wires parsers → normaliser → geocoder → db_writer → notifier to ingest new listings from Nigerian property portals and update existing active listings.
2. **Health Check Runs (Daily)**: Fetches and verifies individual URLs of active feed-absent listings using a voluntary cohort schedule (Adaptive Cooldown) and daily queue caps to confirm removals and price adjustments. It runs in micro-batches (committing results incrementally to PostgreSQL) and is protected by an early-exit timing guard to allow frequent scheduling triggers.

There is no web server, no API, no user interface. It is an autonomous batch script that runs on GitHub Actions (routing requests through a residential proxy tunnel) or directly on local machines.

### The seven stages of every Discovery Run

| Stage | What happens |
|---|---|
| 1. Fetch snapshot | Read all currently ACTIVE listings from the DB into memory |
| 2. Scrape portals | Fetch search result pages and individual listing pages from the active portals |
| 3. Normalise | Convert raw strings (`"₦45M"`, `"3 Beds"`) into typed Python values |
| 4. Geocode | Attach lat/lng coordinates to each listing via neighbourhood name lookup |
| 5. Upsert | Insert new listings, update existing ones, increment missed_run_count, emit history events |
| 6. Run log | Write one row per portal to `scrape_runs` to record what happened |
| 7. Notify | Send a Telegram message with counts and status for each portal |

### The file structure

```
property-scraper/
├── config.py                   ← All configuration (env vars, constants)
├── conftest.py                 ← Root pytest path fix
├── pytest.ini                  ← pytest settings
├── run.sh                      ← Execution wrapper script (runs discovery or health-checks)
├── start_tunnel.py             ← Local residential proxy tunnel daemon (ngrok + local HTTP proxy)
├── .env                        ← Local credentials (never commit)
│
├── scraper/                    ← The application
│   ├── models.py               ← RawListing and NormalisedListing dataclasses
│   ├── orchestrator.py         ← Main entry point — parses args, selects mode, runs pipeline
│   ├── normaliser.py           ← String → typed value conversion
│   ├── geocoder.py             ← Neighbourhood → lat/lng (Nominatim + cache)
│   ├── db_writer.py            ← All database reads and writes
│   ├── health_checker.py       ← Async URL verification and cohort engine (Health Check mode)
│   ├── notifier.py             ← Telegram notification triggers
│   └── parsers/
│       ├── base_parser.py      ← Shared HTTP + pagination infrastructure
│       ├── propertypro.py      ← PropertyPro.ng parser
│       ├── privateproperty.py  ← PrivateProperty.ng parser
│       └── nigeriapropertycentre.py ← NigeriaPropertyCentre.ng parser
│
├── schema/
│   ├── 001_raw_data_schema.sql ← Database tables, indexes — run once
│   └── 002_add_health_check_at.sql ← Adds health check tracking timestamp to schema
│
└── tests/
    ├── conftest.py             ← Shared test helpers and factories
    ├── fixtures/               ← Saved HTML pages from each portal
    ├── test_parsers.py
    ├── test_normaliser.py
    ├── test_geocoder.py
    ├── test_db_writer.py
    └── test_pipeline.py
    └── test_health_checker.py  ← Tests for micro-batched health check execution
```

---

## 2. Configuration (`config.py`)

`config.py` is loaded by every other module. It is always the first import. It reads environment variables and defines all constants that control scraper behaviour.

### Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase PostgreSQL connection string. Required — app crashes immediately if missing. |
| `TELEGRAM_BOT_TOKEN` | Token for the Telegram bot that sends run summaries. Optional — skips notification if absent. |
| `TELEGRAM_CHAT_ID` | The chat/channel ID the bot posts to. Optional. |

In local development these come from the `.env` file. In GitHub Actions they are injected as repository secrets. `python-dotenv` loads `.env` automatically on startup; in Actions `.env` does not exist and the variables are already in the environment.

### Behaviour constants

| Constant | Default | Purpose |
|---|---|---|
| `REQUEST_DELAY_MIN` / `MAX` | 2 / 3s | Delay range between requests |
| `MAX_RETRIES` | 3 | HTTP retry limits |
| `RETRY_BACKOFF_BASE` | 2.0 | Exponential backoff sleep base |
| `REQUEST_TIMEOUT` | 15 | Timeout in seconds |
| `MAX_CONSECUTIVE_FAILURES` | 5 | consecutive errors before aborting |
| `PAGINATION_STOP_AFTER_KNOWN` | 15 | Duplicate stop check range |
| `MISSED_RUN_REMOVAL_THRESHOLD` | 3 | Miss count threshold before checker recruitment |
| `SUSPECTED_SOLD_MIN_DAYS` | 30 | Day range for transaction flag |
| `HEALTH_CHECK_INTERVAL_DAYS` | 2 | Adaptive cooldown check interval |
| `HEALTH_CHECK_LIMIT` | 1000 | Max listings checked per run |
| `HEALTH_CHECK_BATCH_SIZE` | 50 | Micro-batch size for resilient DB commits |
| `HEALTH_CHECK_RUN_INTERVAL_HOURS` | 22 | Daily timing guard limit |
| `UPSERT_BATCH_SIZE` | 200 | DB bulk batch size |

`CANONICAL_NEIGHBOURHOODS` is a hardcoded list of ~100 neighbourhood names (Lagos + Abuja + Port Harcourt). The normaliser uses it for fuzzy matching — raw addresses like `"Lekki Ph1, Lagos"` get matched back to the canonical `"Lekki Phase 1"`. This list is shared with the P0 synthetic data generator.

---


## 3. Data Models (`scraper/models.py`)

There are exactly two data objects in this application. Everything flows through them.

### RawListing

A `RawListing` is what a parser produces. Every field is either a string or `None` — no interpretation, no conversion, no typing. It is a direct mirror of what was in the HTML.

```python
RawListing(
    external_id       = '7NUGY',                                    # ID from the portal URL
    source            = 'propertypro',                              # which portal
    url               = 'https://...',
    title             = 'Newly Furnished 3 Bedroom Luxury Apartment',
    raw_price         = '₦75,000,000/year',                         # raw string, not parsed
    raw_price_type    = 'FOR_RENT',                                  # raw string
    raw_bedrooms      = '3 Beds',                                   # raw string
    raw_bathrooms     = '3 Baths',
    raw_address       = 'Old Ikoyi Ikoyi Lagos',
    raw_floor_area    = None,                                        # not stated on this listing
    description       = 'Spacious luxury...',
    property_type_raw = 'Flat / Apartment',
    agent_name        = 'First Colony Real Estate',
)
```

### NormalisedListing

A `NormalisedListing` is what the normaliser produces from a `RawListing`. Every field is typed. This is what gets written to the database.

Key rules enforced at this stage:

- All prices are stored as **kobo** (int). ₦45,000,000 = `4_500_000_000`. Never floats, never naira.
- All floor areas are stored in **square metres** (float). Sqft inputs are converted.
- `price_parse_failed = True` when a `raw_price` string exists but cannot be interpreted.
- `geocoded` starts as `False` — set to `True` by the geocoder stage.
- `first_seen_at`, `last_seen_at`, `listing_status`, `suspected_sold`, `missed_run_count` are lifecycle fields set by `db_writer`, not the normaliser.

### Why two separate objects?

This separation is intentional. A parser produces a `RawListing` from HTML. The normaliser converts it to a `NormalisedListing`. If the parser breaks, it only affects that portal. If the normaliser breaks, it affects all portals but leaves the parser logic intact.

More importantly: you can test the normaliser with no parsers, no network, no database. You just construct a `RawListing` by hand and pass it in.

---

## 4. Parsers (`scraper/parsers/`)

The parsers are responsible for fetching HTML from portal websites and extracting `RawListing`s from it. There are five files: one shared base class and one subclass per portal.

### `base_parser.py` — Shared infrastructure

`BaseParser` provides everything the portal subclasses need except the actual HTML extraction logic. When you call `parser.scrape()`, this is what runs:

```python
def scrape(self) -> List[RawListing]:
    while current_url:
        html = self._get(current_url)               # fetch search results page
        soup = BeautifulSoup(html)
        listing_urls = self.get_listing_urls(soup)  # ← subclass implements this

        for url in listing_urls:
            ext_id = self._extract_external_id(url)
            if (source, ext_id) in active_listings: # already in DB
                consecutive_known += 1
                if consecutive_known >= PAGINATION_STOP_AFTER_KNOWN:
                    return results                  # ← early exit
                continue

            self._polite_delay()                    # random 2–5s sleep

            if not self._robots_allowed(url):       # robots.txt check
                continue

            html    = self._get(url)                # fetch individual listing
            soup    = BeautifulSoup(html)
            listing = self.parse_listing(soup, url) # ← subclass implements this
            results.append(listing)

        page_number  += 1
        current_url   = self.next_page_url(...)     # ← subclass implements this
```

**What BaseParser handles for you:**

- `requests.Session` with browser-like `User-Agent` and `Accept` headers
- `robots.txt` compliance — fetched at `__init__` time and checked before each listing fetch
- Retry logic — 3 retries with exponential backoff (2s, 4s, 8s) on 429 or timeout
- Random delay between requests — 2 to 5 seconds, uniform distribution
- Pagination short-circuit — stops when `PAGINATION_STOP_AFTER_KNOWN` consecutive listings are already in the DB
- Logging — all fetches, retries, and errors are logged with the portal name as prefix

> **robots.txt note:** The robots.txt checker calls `can_fetch(self.HEADERS['User-Agent'], url)` — **not** `can_fetch('*', url)`. Passing `'*'` is a bug: Python's `RobotFileParser` treats `'*'` as a literal agent name, causing `Disallow: /*type=*` patterns to incorrectly block all URLs. Using the actual `User-Agent` string queries the `User-agent: *` block correctly.

**What each subclass must implement:**

| Name | What it does |
|---|---|
| `source` (attr) | String ID: `'propertypro'`, `'privateproperty'`, etc. Used as the dedup key. |
| `base_url` (attr) | Portal root: `'https://propertypro.ng'` |
| `search_url` (attr) | Starting search page URL |
| `get_listing_urls(soup)` | Returns a list of listing page URLs from a search results page soup |
| `parse_listing(soup, url)` | Returns a `RawListing` from a single listing page soup, or `None` on failure |
| `next_page_url(base, page_n)` | Returns the URL for page N, or `None` when pages are exhausted |

### The three portal parsers

#### `propertypro.py`
- Uses `requests` + `BeautifulSoup` (server-rendered HTML)
- Listing cards on search page: `div.col-md-3`
- External ID: alphanumeric suffix in URL (e.g. `'7NUGY'` from `/property/3-bed-flat-7NUGY`)
- Price: `div.pricing` — e.g. `'₦75,000,000/year'`
- Beds/baths: `div.property-pros li:nth-child(1/2)`
- Address: `div.content-block p` — first paragraph that contains a location
- Agent: `div.sidebar-block01` — truncated before `'View more'`

#### `privateproperty.py`
- Uses `requests` + `BeautifulSoup` (server-rendered HTML)
- Domain: `privateproperty.ng` — **not** `www.privateproperty.com.ng` (that redirects to 404)
- Listing cards on search page: `div.similar-listings-info`
- Price: `p.price` — may be in USD for commercial properties
- Address / property type: `div.property-info h2` — e.g. `'10 bedroom Hotel For Sale Oniru Victoria Island Lagos'`
- Beds/baths: not structured separately — extracted by normaliser from the address `h2`
- Agent: `div.marketed-by p`

#### `nigeriapropertycentre.py`
- Uses `requests` + `BeautifulSoup` (server-rendered HTML)
- Listing cards: `div.wp-block.property.list`
- Price: `span.property-details-price` — e.g. `'₦4,000,000per annum'`
- Address: `div.col-sm-8.f15.property-details address` — uses an `<address>` HTML tag, not `<p>`
- Beds/baths: extracted from structured `itemprop` list in `div.wp-block-footer`
- Description: `div.tab-content`
- Agent: `div.panel-body a strong`

<!-- #### `jiji.py`

> Jiji is different from the other three portals. Its pages are JavaScript-rendered, meaning the listing content is injected by JS after the initial HTML loads. `requests.get()` returns a mostly empty page. Jiji requires Playwright (a headless browser) to execute the JavaScript and produce the full DOM.

- Uses Playwright sync API — launches a headless Chromium browser
- `wait_until='networkidle'` — waits for all JS to finish executing before parsing
- The browser context is reused across all pages in a single run
- `_parse_listing()` still accepts a `BeautifulSoup` object — testable without Playwright
- Price: `div.qa-advert-price-view-title`
- Attributes (type, beds, baths): `div.b-advert-icon-attribute` — repeated element, positional
- Address: `div.b-advert-info-statistics--region`
- Description: `div.qa-advert-description` — `qa-` prefix means it's a stable test hook
- Agent: `div.b-seller-block__name` -->

### Selector constants

Every parser stores its CSS selectors as module-level constants at the top of the file. When a portal changes its HTML, you update one constant, save a new fixture HTML, and run the parser tests. You never need to read through `parse_listing()` to find where selectors are used.

```python
# Example from propertypro.py
LISTING_CARD_SELECTOR = 'div.col-md-3'
PRICE_SELECTOR        = 'div.pricing'
BEDROOMS_SELECTOR     = 'div.property-pros li:nth-child(1)'
BATHROOMS_SELECTOR    = 'div.property-pros li:nth-child(2)'
ADDRESS_SELECTOR      = 'div.content-block p'
```

---

## 5. Normaliser (`scraper/normaliser.py`)

The normaliser takes a `RawListing` (all strings) and returns a `NormalisedListing` (typed). It has no side effects — no network calls, no database. It is a set of pure functions.

The public entry point is `normalise(raw: RawListing) -> NormalisedListing`. Internally it calls eight helpers:

### `parse_price(raw_price: str) → (int | None, bool)`

Returns `(price_kobo, parse_failed)`. Handles all common Nigerian price formats:

| Input | Output (kobo) |
|---|---|
| `'₦45,000,000'` | `4_500_000_000` |
| `'45M'` | `4_500_000_000` |
| `'45.5M'` | `4_550_000_000` |
| `'1.5B'` | `150_000_000_000` |
| `'45 million'` | `4_500_000_000` |
| `'₦75,000,000/year'` | `7_500_000_000` |
| `'₦4,000,000per annum'` | `400_000_000` |
| `'4500000000'` (>10B → already kobo) | `4_500_000_000` |
| `None` / `''` / `'Price on Request'` | `(None, True)` — `parse_failed=True` |

The already-kobo heuristic: if the raw numeric value exceeds `10_000_000_000` (₦10B), it is assumed to already be in kobo. This handles cases where a portal stores prices as kobo internally.

### `parse_floor_area_sqm(raw: str) → float | None`

Converts any floor area string to square metres. Handles: `sqm`, `sq.m`, `m²`, `sqft`, `sq. ft`. Sqft values are multiplied by `0.0929`. Returns `None` if no area is found.

### `parse_integer(raw: str) → int | None`

Extracts the first integer from a string. `'3 Bedrooms'` → `3`. `'4 bed'` → `4`. `'Studio'` → `None`.

### `parse_price_type(raw_type, title, description) → str | None`

Classifies as `FOR_SALE` or `FOR_RENT` by scanning all three fields for keywords. Rent keywords: `rent`, `per year`, `per annum`, `p.a.`, `lease`, `to let`. Sale keywords: `sale`, `for sale`, `outright`, `buy`, `purchase`. Returns `None` if no keywords found (ambiguous).

### `normalise_property_type(raw: str) → str | None`

Maps raw portal property type strings to canonical enum values using `PROPERTY_TYPE_MAP`. Falls back to partial matching (if `'duplex'` appears anywhere in the string → `DETACHED_DUPLEX`). Unknown types are stored as uppercased underscored versions of the raw string.

### `normalise_neighbourhood(raw_address: str) → (str, bool)`

Returns `(neighbourhood_name, was_normalised)`. Three-step strategy:

1. **Exact match:** check if any canonical name appears as a substring in the raw address
2. **Fuzzy match:** split address on commas, run each chunk through `difflib.get_close_matches(cutoff=0.80)` against the canonical list
3. **Fallback:** return the raw address truncated to 60 characters, with `normalised=False`

```
'Lekki Phase 1, Lagos'       → ('Lekki Phase 1', True)
'Lekki Ph1, Lagos'           → ('Lekki Phase 1', True)   # fuzzy matched
'Some New Estate, Ogun'      → ('Some New Estate, Ogun', False)  # stored raw
```

### `infer_city(raw_address, title) → str | None`

Regex patterns check for city-identifying words in the address and title. Lagos is identified by: Lagos, Lekki, Victoria Island, Ikoyi, Ikeja, Surulere, Yaba. Abuja by: Abuja, FCT, Maitama, Asokoro, Wuse, Garki, Gwarinpa.

### `is_diaspora_targeted(description) → bool`

Regex scan against description for keywords: `diaspora`, `forex accepted`, `payment in USD`, `suitable for returnees`, `dollar-denominated`, `expatriate`. Returns `False` if description is `None`.

---

## 6. Geocoder (`scraper/geocoder.py`)

The geocoder takes a list of `NormalisedListing`s and returns the same list with `lat`/`lng` fields populated. It uses Nominatim (OpenStreetMap) — completely free, no API key, no credit card.

### Two-layer cache

The geocoder never sends the same `(neighbourhood, city)` pair to the API twice. It has two cache layers:

| Layer | Where |
|---|---|
| Memory cache | Python `dict` in the `Geocoder` instance |
| DB cache | `raw_data.geocode_cache` table in Supabase |

At `Geocoder.__init__()`, the entire `geocode_cache` table is loaded into the memory dict. After that, all cache checks are in-memory (microseconds). New results are saved to both layers.

After 4–6 weeks of running, you have ~80 unique `(neighbourhood, city)` pairs in the cache. Every run after that makes **zero** Nominatim API calls. The rate limit (1 request/second) is irrelevant at this scale.

### Cache key

The key is `(neighbourhood.lower(), city.lower())` — lowercased to handle inconsistent capitalisation from portals. `'Lekki Phase 1'` and `'LEKKI PHASE 1'` hit the same cache entry.

### Error handling

Every Nominatim failure is handled gracefully. Network error: listing is marked `geocoded=False`, run continues. Empty API response: same. DB save failure: the in-memory cache still has the result, and the listing is still geocoded — only persistence fails.

### Nominatim fair-use requirements

> Nominatim requires: (1) max 1 request/second — enforced by `time.sleep(1.1)` before every call. (2) A descriptive `User-Agent` identifying your application. The `NOMINATIM_AGENT` constant in `geocoder.py` contains a placeholder email — **update it to a real contact before production**. Violating fair-use results in your IP being blocked by OSM.

---

## 7. Database (`scraper/db_writer.py` + `schema/`)

### Schema overview

All tables live in the `raw_data` schema on Supabase. The scraper never touches any other schema.

| Table | Purpose |
|---|---|
| `raw_data.scraped_listings` | One row per listing — current state only. `UNIQUE(source, external_id)`. |
| `raw_data.listing_history` | One row per event (`LISTED`, `PRICE_CHANGE`, `REMOVED`). Foreign key to `scraped_listings`. |
| `raw_data.geocode_cache` | Persistent `(neighbourhood, city)` → `(lat, lng)`. `PRIMARY KEY` on both columns. |
| `raw_data.scrape_runs` | One row per portal per run — operational log with counts and status. |

### `scraped_listings` — the main table

This is the current state of all listings. It does not store history — that goes in `listing_history`. Key design decisions:

- **`UNIQUE(source, external_id)`:** prevents duplicates. `source='propertypro'`, `external_id='7NUGY'` can only exist once.
- **`price_kobo BIGINT`:** all monetary values stored as kobo. ₦45,000,000 = `4_500_000_000`. No floats, no naira.
- **`listing_status`:** `'ACTIVE'` or `'REMOVED'`. Only `ACTIVE` listings are included in the `active_listings` snapshot at run start.
- **`missed_run_count`:** incremented each Discovery Run the listing is absent. Reset to 0 when seen again. If > 0, listing becomes recruited for URL verification via health checker.
- **`suspected_sold`:** `True` when the health checker confirms a listing is removed, provided it was active for ≥30 days with a downward price change in its history.

### DatabaseWriter methods

| Method | What it does |
|---|---|
| `fetch_active_listings()` | Returns `{(source, ext_id): price_kobo}` for all `ACTIVE` listings. Called once at run start. |
| `upsert(listings, active)` | Core write method. Routes each listing to `_insert_new` or `_update_existing`. Detects price changes. Increments `missed_run_count` for feed-absent listings. Returns stats dict. |
| `write_run_log(stats, duration)` | Writes one row per portal to `scrape_runs`. |
| `fetch_geocode_cache()` | Loads all rows from `geocode_cache` into a dict. Called by `Geocoder.__init__()`. |
| `save_geocode_cache(nb, city, lat, lng)` | Inserts a new geocode result. `ON CONFLICT DO NOTHING` — idempotent. |
| `fetch_listings_for_health_check(force_all)` | Returns active listings due for check based on cohort cooldowns (`1.9`/`6.8`/`13.8` days). Limits by `HEALTH_CHECK_LIMIT`. Bypasses constraints if `force_all=True`. |
| `fetch_last_successful_run(source)` | Queries the `raw_data.scrape_runs` table to find the timestamp of the last successful execution of the source (e.g. `'health_check'`). |
| `confirm_listing_removed(listing_id, first_seen)` | Sets status to `'REMOVED'`, checks and marks `suspected_sold`, and logs a `REMOVED` history event. |
| `confirm_listing_active(listing_id, observed_price)` | Resets `missed_run_count` to 0, updates last check timestamp. Logs `PRICE_CHANGE` event if price has adjusted. |


### The upsert logic in detail

`upsert()` is the core write method. Here is exactly what it does:

```python
for listing in listings:
    key = (listing.source, listing.external_id)

    if key in active_listings:
        # Listing already exists — update last_seen_at and mutable fields
        _update_existing(listing)
        stats['updated'] += 1

        # Detect price change
        if listing.price_kobo != active_listings[key]:
            emit history event: PRICE_CHANGE
            stats['price_changes'] += 1
    else:
        # New listing
        _insert_new(listing)   # ON CONFLICT DO NOTHING
        emit history event: LISTED
        stats['new'] += 1

# After all listings processed:
missing = active_listings.keys() - seen_this_run

for (source, ext_id) in missing:
    increment missed_run_count
    # Note: listing_status remains ACTIVE. The health checker will pick this up.
```

### The `suspected_sold` signal

A listing flagged as `suspected_sold` is the application's best guess that a real transaction occurred. The criteria are evaluated exclusively by the health checker when a listing is confirmed removed:

- The listing must have been active for at least 30 days (`SUSPECTED_SOLD_MIN_DAYS`).
- There must be at least one `PRICE_CHANGE` event in history where `new_value < old_value` (price reduction).
- The listing must then be confirmed removed by individual URL check (404/redirect/removal phrase).

This is a proxy signal — not a confirmed sale. Its purpose is to generate pseudo-transaction data for AVM training.

---

## 8. Orchestrator (`scraper/orchestrator.py`)

The orchestrator is the main entry point. It parses CLI arguments to configure the execution mode (Discovery vs. Health Check) and wires all stages together in sequence.

* **CLI filtering**: It supports the `--portals` flag to limit scraping to a comma-separated subset of sources (e.g., `--portals=privateproperty,nigeriapropertycentre`).
* It does not contain database business logic itself — it only handles orchestration sequence, CLI routing, and isolates errors at the portal level.

### Sequence (Discovery Mode)

```python
def run():
    db       = DatabaseWriter(config.DATABASE_URL)
    geocoder = Geocoder(db)                      # ← loads geocode cache from DB

    active_listings = db.fetch_active_listings() # ← snapshot before scraping

    all_raw = []
    for parser in [PropertyProParser, PrivatePropertyParser,
                   NigeriaPropertyCentreParser]:
        try:
            raw = parser(active_listings).scrape()  # ← each portal independent
            all_raw.extend(raw)
        except Exception:
            log.error(...)                           # ← portal failure does NOT stop others

    normalised = [normaliser.normalise(r) for r in all_raw]
    normalised = geocoder.enrich(normalised)
    stats      = db.upsert(normalised, active_listings)

    db.write_run_log(run_stats, duration)
    notifier.send_summary(stats, run_stats, duration)
```

### Sequence (Health Check Mode)

```python
def run_health_checks(force_all=False):
    # 1. Pre-flight check: is database host reachable?
    if not check_database_dns(config.DATABASE_URL):
        return  # Exit cleanly if offline

    db = DatabaseWriter(config.DATABASE_URL)

    # 2. Timing Guard: skip if ran in the last 22 hours
    if not force_all:
        last_run = db.fetch_last_successful_run("health_check")
        if last_run and elapsed_hours < 22:
            return  # Exit early

    checker = HealthChecker(db)
    stats = checker.run(force_all=force_all)

    # 3. Log results to scrape_runs table
    db.write_run_log({"health_check": {...}}, duration)

    # 4. Notify via Telegram
    notifier.send_health_check_summary(stats)
```


### Error isolation

Each portal is wrapped in its own `try/except`. If PropertyPro fails (403, timeout, selector change), the other three portals still run. The failed portal is logged and recorded in `scrape_runs` with status `FAILED`. The Telegram message shows ❌ for that portal.

A single broken parser never takes down the entire run.

---

## 9. Notifier (`scraper/notifier.py`)

The notifier sends a Telegram message at the end of every run. It uses a direct HTTP `POST` to the Telegram Bot API — no library needed.

* **Discovery runs**: The message contains: per-portal status icons (✅/⚠️/❌), new/updated/suspected_sold counts per portal, geocoding success rate, price parse success rate, total run duration.
* **Health check runs**: `send_health_check_summary(stats)` sends checking counts (checked, confirmed active, confirmed removed, price changes, errors).
* **Error reports**: `send_error()` is called by the orchestrator when it catches a critical crash. It sends a short message with the exception text.

If `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are not set, it logs a warning and skips — it does not crash the run.

---

## 10. Tests (`tests/`)

### Philosophy

Every test is fully offline. There are no live network calls, no real database connections. Portals are tested against saved HTML fixtures. The geocoder is tested against a mocked `requests.Session`. The database writer is tested against a mocked `psycopg2` connection.

### Test files

| File | What it tests |
|---|---|
| `test_parsers.py` | Each parser's `parse_listing()` against saved HTML fixtures. Asserts specific field values. |
| `test_normaliser.py` | Unit tests for each normaliser helper function + end-to-end `normalise()` tests with `RawListing` inputs |
| `test_geocoder.py` | Cache init, cache hits, API call behaviour, error handling, batch behaviour |
| `test_db_writer.py` | Upsert routing (new vs existing), price change detection, `suspected_sold` logic |
| `test_pipeline.py` | Parser → normalise → geocode chain without any live calls |

### `conftest.py` files

There are two `conftest.py` files:

- **Root `conftest.py`:** adds the project root to `sys.path` so that `from scraper.models import ...` works regardless of which directory you run pytest from.
- **`tests/conftest.py`:** shared factories (`make_raw()`, `make_normalised()`), mock helpers (`mock_db()`, `mock_nominatim()`), and the `load_fixture()` function.

### HTML fixtures

`tests/fixtures/` contains saved HTML pages from each portal. These are committed to the repo. When a portal changes its HTML and a selector breaks:

1. Run the scraper — it will return 0 listings for that portal and log the issue
2. Open the live portal listing in your browser, save the page source as UTF-8 HTML
3. Replace the file in `tests/fixtures/`
4. Run `pytest tests/test_parsers.py` — the failing test tells you exactly which field selector needs updating
5. Update the relevant `SELECTOR` constant in the parser file
6. Run pytest again to confirm

### Running tests

```bash
pytest                                                          # all tests
pytest tests/test_normaliser.py                                 # normaliser only — fastest, pure logic
pytest tests/test_parsers.py                                    # parser selectors + fixture parsing
pytest tests/test_geocoder.py                                   # geocode cache and API mocking
pytest tests/test_db_writer.py                                  # upsert and business logic
pytest tests/test_pipeline.py                                   # full parser→normalise→geocode chain

# Run a single class
pytest tests/test_parsers.py::TestPropertyProParser -v

# Run a single test
pytest tests/test_parsers.py::TestPropertyProParser::test_price_raw -v
```

---

## 11. Running the Scraper (`run.sh`)

`run.sh` is the execution wrapper script. It sets up the environment and runs the pipeline in the selected mode.

### Running commands:
* **Discovery Mode**: `./run.sh`
* **Health Check Mode**: `./run.sh --health-check` (only checks listings due based on adaptive cooldown)
* **Force Health Check**: `./run.sh --health-check --all` (force-checks all active listings immediately, bypassing cohort cooldown constraints)

### What `run.sh` does:
1. Check `.env` exists and `DATABASE_URL` is set
2. Initialise pyenv so `python3.12` is on `PATH` (pyenv shims are not active in scripts by default)
3. Walk `python3.12` → `python3.11` → `python3.10` → `python3` and pick the first found
4. Create `.venv/` if it does not exist
5. If `.venv/` was built against a different Python version, delete and rebuild it
6. `pip install -r requirements.txt`
7. `playwright install chromium` (no-op if already cached)
8. Apply schema to Supabase (idempotent — `IF NOT EXISTS` guards everywhere)
9. `python3 -m scraper.orchestrator "$@"` (passes arguments to the orchestrator)
10. Print summary with run duration; on failure, print last 30 lines of `scraper.log`

### The `.env` file

`.env` sits in the project root and is never committed to git. It provides the secrets that `config.py` reads:

```
DATABASE_URL=postgresql://postgres.[project-id]:[password]@...
TELEGRAM_BOT_TOKEN=1234567890:ABCDEF...
TELEGRAM_CHAT_ID=123456789
```

---

## 12. Full Data Flow — Discovery Run

```
./run.sh
└─ python3 -m scraper.orchestrator

   ├─ config.py loads .env → DATABASE_URL, TELEGRAM_*, constants

   ├─ DatabaseWriter connects to Supabase
   │   └─ SELECT all ACTIVE listings → active_listings dict

   ├─ Geocoder
   │   └─ SELECT all geocode_cache rows → memory_cache dict

   ├─ PropertyProParser(active_listings).scrape()
   │   ├─ GET /property-for-sale?per_page=24 (search page)
   │   ├─ BeautifulSoup → get_listing_urls() (div.col-md-3)
   │   └─ for each URL:
   │       ├─ check active_listings → skip if known
   │       ├─ sleep 2–5s
   │       ├─ GET listing URL
   │       └─ parse_listing() → RawListing

   ├─ (same for PrivateProperty, NigeriaPropertyCentre)

   ├─ normaliser.normalise(raw) for each RawListing
   │   ├─ parse_price()               '₦75M/year'          → 7_500_000_000
   │   ├─ parse_price_type()                               → 'FOR_RENT'
   │   ├─ parse_integer()             '3 Beds'             → 3
   │   ├─ normalise_property_type()   'Flat / Apartment'   → 'FLAT_APARTMENT'
   │   ├─ normalise_neighbourhood()   'Old Ikoyi Ikoyi Lagos' → 'Ikoyi'
   │   ├─ infer_city()                                     → 'LAGOS'
   │   └─ is_diaspora_targeted()                           → False

   ├─ geocoder.enrich(normalised)
   │   └─ for each listing:
   │       ├─ check memory_cache → (lat, lng) if hit
   │       └─ cache miss: GET nominatim.openstreetmap.org → save to both caches

   ├─ db.upsert(normalised, active_listings)
   │   ├─ new:     INSERT → emit LISTED history event
   │   ├─ existing: UPDATE last_seen_at, price → emit PRICE_CHANGE if changed
   │   └─ missing: increment missed_run_count

   ├─ db.write_run_log(stats, duration)
   │   └─ INSERT INTO raw_data.scrape_runs (one row per portal)

   └─ notifier.send_summary()
       └─ POST https://api.telegram.org/bot.../sendMessage
```

## 12.1. Full Data Flow — Health Check Run

```
./run.sh --health-check
└─ python3 -m scraper.orchestrator --health-check

   ├─ check_database_dns() (Pre-flight network check)
   │  └─ If offline -> log warning and exit cleanly

   ├─ DatabaseWriter checks timing guard:
   │  └─ SELECT run_at FROM scrape_runs WHERE source = 'health_check' AND status = 'SUCCESS'
   │  └─ If elapsed < 22 hours (and force_all is False) -> log skip and exit early

   ├─ DatabaseWriter fetches candidate listings:
   │  └─ SELECT listings where status = 'ACTIVE' and missed_run_count > 0 due based on age cohort cooldown
   │     ordered by missed_run_count DESC, last_check ASC
   │     capped by LIMIT 1000 (HEALTH_CHECK_LIMIT)

   ├─ Orchestrator slices candidate list into batches (HEALTH_CHECK_BATCH_SIZE, e.g. 50)
   │
   ├─ For each micro-batch (processed sequentially):
   │   │
   │   ├─ HealthChecker runs async network verification (Phase 1):
   │   │   ├─ Opens aiohttp.ClientSession
   │   │   ├─ Fans out requests using Semaphore (default 50 concurrency)
   │   │   ├─ For each candidate URL in the current batch:
   │   │   │   ├─ Apply delay jitter
   │   │   │   ├─ GET listing URL
   │   │   │   ├─ If 404 / redirect / deletion phrase -> is_removed = True
   │   │   │   ├─ If 200 -> extract price
   │   │   │   └─ If network timeout/error -> preserve ACTIVE state
   │   │
   │   └─ DatabaseWriter writes batch checks immediately (Phase 2):
   │       ├─ If is_removed = True:
   │       │   ├─ UPDATE status to 'REMOVED', evaluate suspected_sold
   │       │   └─ INSERT history event: REMOVED
   │       └─ If is_removed = False:
   │           ├─ Reset missed_run_count = 0, stamp check time
   │           └─ If price changed -> UPDATE price_kobo and INSERT event: PRICE_CHANGE
   │
   ├─ db.write_run_log() (Writes source='health_check' SUCCESS log)
   │
   └─ notifier.send_health_check_summary(stats)
```


---

## 13. Debugging — What Goes Wrong and Where

### Portal returns 0 listings

The most common failure. Causes in order of likelihood:

- **Selector drift:** the portal changed its HTML. Check `LISTING_CARD_SELECTOR` in the parser. Run `diagnose.py` to get fresh HTML, inspect in browser DevTools.
- **403 Forbidden / Cloud Blocking:** Bot detection blocking cloud subnet ranges (e.g. GitHub Actions runners). Make sure the local residential proxy tunnel (`start_tunnel.py`) is active and repository secrets on GitHub are synced with the tunnel address. Note: portals like propertypro.ng and privateproperty.com.ng also block public VPNs/exit nodes (like WARP and Tor exit nodes).
- **Playwright timeout:** Jiji's JS did not finish loading. `SELECTOR_TIMEOUT` is 20 seconds — increase if needed.
- **robots.txt false positive:** verify `robots.txt` manually. The fix was changing `can_fetch('*', url)` to `can_fetch(HEADERS['User-Agent'], url)`.

### ngrok Tunnel Connection Drops (ProxyError)

- **Symptom**: GHA runner workflow fails with:
  `ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))`
- **Cause**: Censorship firewalls or restrictive ISPs using Deep Packet Inspection (DPI) or TCP Resets (RST) to terminate ngrok tunnels.
- **Fix**: The scraper's built-in `MAX_RETRIES = 3` with exponential backoff handles this. If drops are very frequent, modify the ngrok launch command in `start_tunnel.py` to specify an alternate server region (e.g. `ngrok tcp 8118 --region eu`).

### systemd Tunnel Output Logs Frozen

- **Symptom**: Checking the logs via `journalctl --user -u scraper-tunnel.service -f` shows no request proxying output.
- **Cause**: Python buffers standard output by default when stdout/stderr is redirected to a non-interactive console.
- **Fix**: Ensure that `Environment=PYTHONUNBUFFERED=1` is specified in the systemd service template inside the `[Service]` section.

### Health Check script exits immediately without performing checks

- **Cause**: The application-level Timing Guard is preventing redundant checks. If a successful check completed less than 22 hours ago, it will skip execution.
- **Fix**: Run the command with the `--all` or `--force` flag (e.g. `./run.sh --health-check --all`) to bypass the guard.

### Health Check outputs "Pre-flight network check failed" and exits

- **Cause**: The script cannot resolve the database connection hostname (DNS lookup failed). This indicates your internet connection is down or DNS is misconfigured.
- **Fix**: Verify your network connectivity. The script exits cleanly to avoid raising critical database connection alarms while offline.

### `ModuleNotFoundError: No module named 'scraper'`


- pytest is not finding the project root. Ensure root `conftest.py` exists and inserts the project root into `sys.path`.
- Run `pytest` from the project root directory, not from inside `tests/`.

### `psycopg2-binary` build failure

- You are running Python 3.13. `psycopg2-binary==2.9.9` has no pre-built wheel for 3.13.
- Fix: use Python 3.12 (`pyenv install 3.12.9 && pyenv local 3.12.9`), delete `.venv` and re-run.
- Or: upgrade to `psycopg2-binary==2.9.10` which has 3.13 wheels.

### `TypeError: argument of type 'module' is not iterable`

- A parser was constructed with `config` (the module) instead of `active_listings` (the dict).
- Old scaffold passed `config` to parsers. Current orchestrator passes `active_listings`. Replace `orchestrator.py` with the current version.

### `playwright install` fails with `libasound2` error

- GitHub Actions runs Ubuntu 24.04 (Noble) which renamed `libasound2` → `libasound2t64`.
- `playwright install --with-deps` uses a hardcoded script that still requests the old name.
- Fix: install Chromium deps manually (`libnss3`, `libatk1.0-0t64`, etc.) then run `playwright install chromium` without `--with-deps`.

### Geocoder always returns `geocoded=False`

- Check that `NOMINATIM_AGENT` in `geocoder.py` is set to a real application name and contact email — Nominatim may block generic or empty User-Agents.
- The memory cache is empty on first run — every unique neighbourhood makes one API call. The 1.1 second sleep between calls means 80 neighbourhoods takes ~90 seconds. This is normal.

---

## 14. Ongoing Maintenance

### When a portal changes its HTML (expected regularly)

1. Run `./run.sh` — Telegram shows ❌ or 0 listings for the affected portal
2. Open the live portal in browser, navigate to a listing
3. DevTools → Inspector, find the element wrapping the broken field
4. Update the relevant `SELECTOR` constant in `scraper/parsers/<portal>.py`
5. Save the page source to `tests/fixtures/<portal>_listing.html`
6. `pytest tests/test_parsers.py::Test<Portal>Parser -v`
7. If tests pass, run `./run.sh` again

### Adding a new portal

- Create `scraper/parsers/newportal.py` — subclass `BaseParser`, define `source`/`base_url`/`search_url`, implement `get_listing_urls()`, `parse_listing()`, `next_page_url()`
- Add `NewPortalParser(active_listings)` to the parsers list in `orchestrator.py`
- Save a fixture HTML page to `tests/fixtures/newportal_listing.html`
- Add a `TestNewPortalParser` class to `test_parsers.py`

### Refreshing the canonical neighbourhood list

Edit `CANONICAL_NEIGHBOURHOODS` in `config.py`. This list is shared with the P0 synthetic data generator — update P0's copy too. New neighbourhoods start appearing in the DB immediately; old ones remain matched.
