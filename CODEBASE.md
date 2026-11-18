# Getting to know property-scraper

This is the guide to read when you want to understand what this project does,
follow a questionable value back to its source, or change something without
breaking the projects that use its data. Start here; the smaller domain guides
linked below contain the detailed rules and operating commands.

The project has grown into a data pipeline. Fetching a page is only the first
part. We now need to distinguish what an agent wrote, what a parser extracted,
what the rules concluded, what a person reviewed, and what an application is
allowed to assume. Keeping those layers visible is what makes the data useful.

This guide was checked against the code on 19 November 2026. Operational counts
change as discovery and verification run. Read the coverage views for current
figures; a dated audit report is a snapshot, not today's live database.

## Read the project in this order

If you have an hour, read the example below, the pipeline walkthrough, the database
section and the operating notes. Then follow one parser through `normalise()` and
`DatabaseWriter`. You do not need to understand every audit table first.

For a shorter orientation, read [ARCHITECTURE.md](ARCHITECTURE.md). For the full
database dictionary, read [docs/database.md](docs/database.md). The maintained
rule/operations guides are:

- [Property types](docs/property-types.md): forms, facets, aliases and unresolved types.
- [Property counts](docs/property-counts.md): units, layouts, room evidence and verification.
- [Unified consumer contract](docs/property-unification.md): the supported research reader.
- [Pricing](README.md#rental-prices-and-billing-periods): quote units and comparable rental data.

Files under `docs/archive/` explain past proposals and snapshots. They remain
useful evidence, but the current guides and installed schema determine behavior.
The user's original review CSV is historical input; editing it is not a database
update. Runtime reviewed decisions live in `scraper/property_reviews.json`.

## One advert, several different facts

Suppose an agent advertises a block containing four flats, each with three
bedrooms and two bathrooms, and mentions a swimming pool. Here is how to think
about the result:

| Question | What the structured data should say |
| --- | --- |
| What is the advertised form? | `BLOCK_OF_FLATS` |
| What is its scope? | A whole building, where the source establishes that scope |
| What does it contain? | Four dwelling units, with a contained-unit relationship |
| What is each dwelling's layout? | Three bedrooms and two bathrooms, because the wording explicitly says each flat |
| What feature is advertised? | A pool claim, with ownership/shared scope left unknown unless stated |
| How many assets does one price buy? | A separate offer question; do not infer it from the number of flats |

This is why the type should not become `FOUR_UNITS_OF_THREE_BEDROOM_WITH_POOL`.
Type, quantity, layout, amenity, offer and price basis are different dimensions.
A broad type can be accurate while one of those other dimensions remains unknown.

Also, one row is a **portal listing**. Two portals can advertise the same physical
property, and one advert can describe several units. The database currently does
not claim to have solved physical-property identity across portals.

## What happens during discovery

The entry point is [scraper/orchestrator.py](scraper/orchestrator.py). Discovery
loads the active inventory, asks each enabled portal for recent listings, turns
raw strings into structured data, attaches approximate location coordinates, and
writes observations to PostgreSQL. Per-portal failures are isolated so one broken
portal does not discard the other portals' results.

### 1. Portal code reads the page

The enabled parsers are PropertyPro, Private Property and Nigeria Property Centre.
A Jiji parser exists, but it is disabled in the orchestrator. Its browser dependency
is not needed by the three enabled parsers, although `run.sh` currently installs
Chromium as part of its general setup.

[BaseParser](scraper/parsers/base_parser.py) supplies a requests session, robot
policy handling, delay/retry behavior and feed pagination. Each portal module
knows its listing URLs and HTML layout. The parser returns a `RawListing` from
[models.py](scraper/models.py): source identity, title, description, raw price,
raw type, raw room strings, raw area and other source fields.

Keep field extraction tied to the primary listing. A number in a related-property
card or a page-wide feature list is not evidence for the advertised property.
[room_metrics.py](scraper/parsers/room_metrics.py) scopes bedroom/bathroom widgets,
identifies labels/schema properties or recognized icons, and excludes toilets.
An unknown icon shape is a gap to investigate, not a reason to guess by position.

[listing_identity.py](scraper/parsers/listing_identity.py) checks the requested,
redirected and canonical listing identity. An ID occurring inside a longer ID or
only in a query parameter is not a match. A renamed URL with the same ID remains
usable, and its current URL supplies parsing context. Health treats foreign-host
or canonical conflicts as errors rather than accepting another advert's data.
The writer rejects a foreign `(source, external_id)` observation before any write.

Pagination stops after enough consecutive known listings. This keeps ordinary
discovery cheap, but it is not a complete rescrape of every listing. Changing a
parser does not automatically repair all old rows.

### 2. Normalisation interprets raw strings

[normaliser.py](scraper/normaliser.py) creates a `NormalisedListing`. It calls the
pricing, property-type, room and area assessors rather than treating every field as an
isolated integer conversion. It also normalizes neighbourhood labels, infers a
city from text and detects the diaspora-marketing flag.

Prices are integer **kobo**. NGN 45 million is 4,500,000,000 kobo. The quote's
purpose, period, period count, currency and basis travel with the amount. A bare
amount is insufficient to compare a monthly flat, a daily short let and a sale.

`neighbourhood` is the resulting name. `neighbourhood_normalised` is a boolean
saying whether it matched the canonical vocabulary; it is not another name field.
Unknown values remain explicit. An unknown quantity does not become one or zero.

### Area quantities need their own interpretation

[area_measurements.py](scraper/area_measurements.py) reads titles, descriptions and
labelled fields collected by [area_metrics.py](scraper/parsers/area_metrics.py).
“House on 600 sqm, floor area 250 sqm” produces two quantities with different roles.
“500 sqm apartment” retains a size claim with an unspecified role. It does not
silently become a 500 sqm floor. A generic portal **Size** widget is handled the
same way. Old checkpoints with the previous page-wide Size selector are retained
as unscoped evidence, not trusted floor fields.

Square feet, hectares and international acres convert to sqm. Claims retain the
original text, amount, unit, conversion, basis and approximate wording. Plots have
no assumed conversion. Rates, ranges, bounds, conflicting values, ancillary-feature
sizes and unclear per-unit/shared-site claims stay available with review reasons.
The extractor is deliberately bounded; absence of a supported scalar does not
mean the advert contains no clues. Unsupported spellings and formats need review.

[area_store.py](scraper/area_store.py) fills missing supported land/floor fields and
preserves existing non-null areas. It keeps a first legacy snapshot and an audit
in the existing fact-assessment table. A new advert that contradicts an old area
marks it unverified; it does not overwrite it. Only a retained legacy floor value that equals the old one-decimal sqft conversion
can use a rounding match. New floor and land values require exact scalar agreement. The original claim
still carries the exact conversion and the stored scalar uses two decimal places.

After migration 015, use `research.properties.supported_floor_area_sqm` and
`supported_land_area_sqm`, together with their statuses and `area_evidence`.
The `stored_*` fields retain unsupported numbers. `research.area_measurements`
exposes individual claims, including held ones: `claim_usable` alone does not
resolve a conflict between claims. Check the final field status as well.

### 3. Geocoding supplies an approximate area location

[geocoder.py](scraper/geocoder.py) looks up a neighbourhood/city pair through
Nominatim and caches successful coordinates in memory and `geocode_cache`.
The configured contact email goes in the user agent. The code delays uncached
requests and reuses cached results.

These are usually neighbourhood-level coordinates. `geocoded=True` does not mean
someone verified the property's position or found its parcel boundary. That
matters for valuation and spatial studies: many adverts can share one centroid.
The geocoder does not establish land size or measure building footprints.

Location refresh is currently partial. Discovery can refresh coordinates while
retaining older address/neighbourhood/city labels; full health observations do
not refresh every location field. A fresh room assessment therefore does not
certify location freshness. A useful next change is to refresh and version those
fields together, with review when a portal ID appears to have been reused.

### 4. The writer commits changes and their history together

[db_writer.py](scraper/db_writer.py) coordinates inserts, discovery updates and
identity-matched health observations. It works with dedicated stores:

| Module | What it owns |
| --- | --- |
| `property_storage.py` | Canonical classification and before/after classification history |
| `room_count_store.py` | Stored rooms, raw metrics, evidence, retained originals and room audit |
| `area_store.py` | Land/floor claims, supported gap fills, retained originals and area audit |
| `property_count_store.py` | Quantity assessments, observations, decisions and feature/offer assessments |
| `pricing.py` and the writer | Quote interpretation, comparison and pricing/lifecycle events |

The stores are real database writers too; it is inaccurate to say every SQL write
lives in `db_writer.py`. Their APIs generally use the caller's transaction. A
listing update and its evidence should commit together, or roll back together.

Discovery deduplicates input by `(source, external_id)` before writing, and the
database has the same unique key. An existing removed advert can be relisted;
that is different from inserting a second row for the same portal identity.
Absence from a successfully scraped feed increments a missed-run counter. It
does not establish that the advert was removed or the property was sold.

## What happens during a health check

[health_checker.py](scraper/health_checker.py) fetches saved listing URLs. Network
requests run concurrently; database writes run on the main thread after each
micro-batch. Current defaults are 50 listings per batch, ten concurrent requests
in total and three per portal, with two-to-five-second jitter and bounded retries.
These are configuration values, not promises of a fixed completion time.

The normal candidate queue contains active, feed-absent listings whose next check
is due. Its age cohorts are 1.9, 6.8 and 13.8 days; the normal run cap is 1,000.
An additional run-interval guard can make an hourly trigger exit without work.
Confirming an advert active resets its missed count. It needs to be missed by
discovery again before entering the ordinary queue.

This distinction is easy to miss: **an hourly timer does not mean every listing
is verified hourly, or even that every trigger makes portal requests**. `--all`
bypasses the normal queue restrictions and timing guard, so reserve it for a
reviewed operation rather than a routine debugging command.

A successful identity-matched observation refreshes source/classification and
room/count/feature evidence in the existing transaction. A price-only repair does
not pretend to be a new property observation. A removal event is evidence about
the advert's availability, not proof of a completed sale, rent or transaction date.
`suspected_sold` is a heuristic, not a transaction record.

`first_seen_at` is when this pipeline first saw the advert. `last_seen_at` tracks
discovery observations. `last_health_check_at` tracks health checks. None is an
independently verified construction date, agent publication date or sale date.

## How the interpretation modules fit together

### Forms and facets

[property_types.py](scraper/property_types.py) defines `property-types-v3`, its
39 canonical forms and the matching rules. Classification is I/O-free: it can be
exercised with a string and a fixture without making requests or database writes.
Specific phrases, source context, negations, ancillary buildings, alternate offers
and reviewed cases affect the decision. Raw labels are retained separately.

Read `property_type_status` alongside the canonical value. `CLASSIFIED` means the
rules have adequate source evidence for that form. `INSUFFICIENT_EVIDENCE`,
`AMBIGUOUS` and `UNSUPPORTED` explain different gaps. `LEGACY_UNREVIEWED` is for
old input/checkpoints; the completed historical rollout removed that state from
production listings. Canonical type codes are not arbitrary cleaned source text.

The family/category/facets answer broader or independent questions. For example,
a maisonette remains a form, bedrooms remain a layout, a cinema is a feature, and
a home office does not silently add a bedroom. A self-contained advert is not
forced into a bedroom count unless its wording supplies that count.

### Quantities and layout claims

[property_count_profile.py](scraper/property_count_profile.py) finds literal
quantity phrases and context. [property_counts.py](scraper/property_counts.py)
turns eligible phrases into normalized claims and proposed decisions under
`property-counts-v2`.

An observation records its entity, relationship, exact/range bounds, parent and
offer references, rule, evidence and review flags. The decision is separate:
ACCEPT, HOLD, REJECT or REVOKE. Two units contained in a building are different
from two buildings offered together or two units still available in a development.
Do not sum them into one unqualified `unit_count`.

### Bedrooms and bathrooms

[room_counts.py](scraper/room_counts.py) reconciles separate primary metrics,
explicit source wording and applicable layout reviews. Legacy numbers are not
proof of correctness, but a selector defect is not proof they are wrong either.

The historical backfill preserved every existing non-null bedroom/bathroom value.
It filled previously empty fields only where explicit evidence supplied a count.
Future corrections require a fresh, unambiguous primary metric. Missing or
conflicting observations do not erase a stored number. PropertyPro can also supply positive structured room counts on pages without
visible widgets. The residence name must match the canonical-URL-bound primary
advert; zero defaults and related residences do not become metrics.

The first pre-repair pair
remains in `room_count_legacy`; each assessment retains before/after evidence.

For each field, distinguish the stored number from the extracted candidate, its
status and its basis. `KNOWN` means supported as advertised, not independently
physically inspected. `UNVERIFIED` means a retained number lacks sufficient
consistent supporting evidence. UNKNOWN, AMBIGUOUS, MIXED_LAYOUT, REVIEW_REQUIRED,
NOT_APPLICABLE and PENDING describe other evidence or freshness conditions.

Review flags explicitly call out 100+ counts, other large counts, possible joined
digits, unexplained zeroes, negatives, room counts on land, unusual ratios and
source conflicts. They are not confirmed-error totals. A hotel-wide quantity
needs a different basis from bedrooms per flat. A labelled widget still needs
scope/range validation; different bedroom layouts do not establish that a single
bathroom total applies to every dwelling.

Do not infer bathrooms from bedroom counts, toilet counts, ensuite wording or a
typical layout. Keep confidence separate for each field: a missing bathroom does
not invalidate a supported bedroom or canonical form.

A retained number and a supported wording claim are also different things. A saved
title might explicitly say three bedrooms while the legacy column still holds
1,234. The column stays unverified until an audited correction is justified;
the separately retained candidate can still be a supported claim about the advert.
The ordinary per-dwelling columns use the stricter stored-number policy. If a study
intentionally analyzes source wording, inspect that evidence separately:

```sql
SELECT listing_id, stored_bedrooms, bedrooms_status,
       (room_count_evidence->'bedrooms'->>'value')::integer AS source_bedroom_claim,
       room_count_evidence->'bedrooms'->'claims' AS supporting_claims
FROM research.properties
WHERE room_counts_current
  AND room_count_evidence->'bedrooms'->>'evidence_status' = 'KNOWN'
  AND room_count_evidence->'bedrooms'->>'basis' = 'PER_DWELLING';
```

Report that method as source-supported claims, keep the retained column/status
alongside it, and check source age. This query neither changes stored values nor
certifies a physical inspection. Do not use an unresolved or mixed-layout candidate
as an unqualified unit count.

### Features, offers and human review

[property_facts.py](scraper/property_facts.py) extracts feature claims, explicit
negatives, scope and offer questions. `current_property_facts` concerns that fact
kind; later room assessment rows do not overwrite feature interpretations simply
because they share a history table.

[property_reviews.py](scraper/property_reviews.py) reads the reviewed-case registry.
A decision binds portal identity to an exact raw-label/title/description hash.
That prevents a review of one saved advert from silently approving a changed
version. The original CSV remains evidence of the discussion, not an executable
spreadsheet whose edited cells automatically change production.

## Find your way around the database

PostgreSQL calls a namespace a schema. `raw_data` currently holds operational
listing state, derived evidence and audit bookkeeping. Its name does not mean
every column contains untouched portal text. A view is a saved query; it does not
store another full copy of every property.

Migration 014 introduces the smaller `research` schema. Until it is installed,
use `raw_data.property_research_current` and `raw_data.property_review_queue`.
After installation, everyday entry points are:

| Object | Start here when you want to… |
| --- | --- |
| `research.properties` | Read one row per listing, interpretations, retained counts, source text and location |
| `research.review_queue` | Investigate outstanding questions and explicit room flags |
| `research.room_count_coverage` | Measure support and gaps by field, portal, category and lifecycle |
| `research.area_measurements` | Inspect each size claim, its land/floor role, units, scope and held reasons |

The 17 physical tables have different jobs. `scraped_listings` is current state.
Vocabulary tables constrain canonical forms. Count assessments/observations/
decisions preserve structured claims and review actions. Fact assessments retain
features/offers and room evidence. Classification/pricing/lifecycle histories
explain changes. Operation manifests and receipts make repairs resumable. The
geocode cache and scrape-run log support operations.

See [the database dictionary](docs/database.md) before querying an unfamiliar
table. Do not delete an audit table because it resembles another one. Moving
objects to separate `audit`/`ops` schemas would require dependency, permission and
migration changes; the consumer views and object descriptions are the safe first
cleanup. Migration 014 does not move or duplicate listing data or grant anonymous
access. Its views use the caller's existing underlying privileges.

### Fresh source is different from fresh data and correct data

The current views compare evidence hashes with saved source text and context.
Changing the source hides stale interpretations until reassessment. A price-only
change need not invalidate unrelated text evidence. Reversal appends history
rather than erasing the fact that an earlier decision existed.

`contract_current` describes applicability of the interpretation contract. It is
not a claim that every bedroom, bathroom, feature, coordinate and price is verified.
A current assessment can correctly say that a stored bathroom count is unverified.
Also, a source hash can still match an advert last fetched months ago. Check age
and lifecycle separately from interpretation freshness.

## Give dependent projects an explicit data contract

Use the research reader instead of rediscovering rules from raw source labels.
The current room-aware contract is `property-research-v2`. State the version,
filters, extraction date and unresolved coverage in an analysis or export.

For example, bedroom-dependent work can select supported per-dwelling bedrooms
without requiring a supported bathroom:

```sql
SELECT listing_id, source, property_type, city, neighbourhood,
       bedrooms_per_dwelling, bathrooms_status,
       price_kobo, price_type, price_period, price_period_count
FROM research.properties
WHERE contract_current
  AND listing_status = 'ACTIVE'
  AND property_type_status = 'CLASSIFIED'
  AND bedrooms_status = 'KNOWN'
  AND bedrooms_per_dwelling IS NOT NULL;
```

For a cautious study, inspect/exclude relevant outstanding review flags too.
Bathroom-dependent work needs a bathroom status/basis filter of its own. Do not
drop whole listings from every analysis merely because one field lacks support.
Retained unverified numbers are available as `stored_bedrooms` and
`stored_bathrooms`; exploratory work can include them with disclosed assumptions
and compare results with the supported subset.

For prices, keep sale, rent and short-let purposes separate. A quote per month,
night, year, person or square metre is not interchangeable with a property-level
sale amount. Even a `single_unit_price_candidate` still needs relevant field
quality, location, period and comparable-asset checks. Never divide a bundle price
by a count until that relationship is established. A supported three-bedroom
layout inside a block does not establish that the asking price buys one flat.
For a simple unit-price cohort, require unit scope and a suitable price basis;
review whole-building and bundle offers separately.

`raw_data.comparable_rental_prices`, `rental_price_summary` and
`rental_pricing_coverage` support current rental comparisons. The legacy
`rebuild_snapshots.py` command is deliberately disabled because its old historical
series mixed incompatible quote units. It does not rebuild trustworthy history
from today's listings, and existing historical tables are not silently rewritten.

## Operate the project without guessing

### Normal runs

From the repository root, with the intended environment configured:

```bash
python -m scraper.orchestrator                 # Discovery
python -m scraper.orchestrator --health-check  # Normal health queue
./run.sh --preview                            # Local static dashboard preview
```

`run.sh` also initializes Python/dependencies, loads `.env`, installs browser
assets and replays the numbered SQL files. The GitHub scraper workflows replay
SQL too. Running a read-only preview command is different: it does not migrate
the schema or repair production data.

Telegram summaries are sent by normal orchestration when credentials are set.
The targeted production room verification operation uses the merged stores/writer
directly and does not send notifications or mark unavailable adverts removed.

### Checkpoints and repair artifacts

The ordinary discovery/health checkpoint is `.scraper_checkpoint.json`, with a
mode and timestamp; it expires after 24 hours. It helps resume interrupted work,
but is not a historical source archive or evidence that every write committed.

Controlled repair tools use frozen reports, target/rule/source fingerprints, UUID
run manifests and durable per-listing receipts. Keep the exact original release,
artifact and run selection when resuming. A new rule or selection needs a new
reviewed artifact/run. A completed retry attempts zero rows. Reversal protects
later edits and does not remove audit history.

Use the [unified operations guide](docs/property-unification.md) for the combined
runner and [room operations](docs/property-counts.md) for room preview/apply/
reversal and primary-page verification. The rental recovery subsystem has its own
policy, SQLite progress ledger, budgets and timers in the recovery modules/scripts;
it is not the same checkpoint or the room-repair receipt mechanism.

Private reports belong under ignored `.local/`. Source snapshots may contain
publicly advertised contact details; keep artifacts private and out of PR bodies.
Some completed generated JSONL reports were archived as verified `.jsonl.gz`
files during the November rollout. Decompress a copy before using a tool that
expects the original JSONL bytes; preserve the recorded uncompressed checksum.
Editable worksheets are separate from those frozen artifacts.

### Getting a current room worksheet

Run [export_room_review.py](scripts/export_room_review.py) with an ignored output
directory, as shown in [the room guide](docs/property-counts.md#export-a-current-room-worksheet).
It reads the current consumer contract and writes separate full, exceptional and
100-plus CSVs. Optional verification logs distinguish inaccessible pages, changed
assets, supported candidates and pages that still omit the quantity. Missing logs
are not evidence that a listing was never visited.

Each export has a unique name and a `current.json` pointer. Your older review notes
remain in their original file. Check the snapshot date and source hash before
acting on an old row. The blank review columns collect checked values and evidence;
editing them does not write to production. A decision still needs a source-bound,
audited repair. Work on the exceptional active listings first, then by action code.

### Current operational handoff

At 14:24 UTC on 18 November 2026, merged PR #17 had been deployed and verified
across 28,955 listings. All original non-null room values and protected non-room
fields survived the backfill; 729 bedroom gaps and seven bathroom gaps were filled.
The v2 reader and all room assessments were current. That is the preservation
baseline; later primary observations can legitimately correct supported values.

The first live verification batch attempted 96 listings. Its canary exposed
additional ratio/layout validation gates. PR #18 added the tested guards and bulk
room-only observations and was merged/deployed. Two provisional bathroom writes
were reversed/reassessed with prior values restored and advertised claims retained;
293 potentially affected assessments were checked without other numeric changes.
The restarted pass keeps the earlier checkpoint and excludes previously attempted
records. Live verification progress, updates and unresolved outcomes are in:

- `.local/room-counts/active-rollout.json`: backup, canary, full repair and verification.
- `.local/room-counts/active-verification.json`: the current primary verification pass.
- `.local/room-counts/active-verification-initial.json`: the preserved first-batch checkpoint.
- `.local/room-counts/ops/`: archived operation helpers and their checksums.

Do not mistake an initial preview or pilot for applied production improvements.
For the latest field coverage, query the coverage view rather than adding dated
report figures together. The original raw-type review CSV remains unchanged.

The local `scraper-health.timer` was active before rollout and was temporarily
paused for the coordinated operation; restore it after verification. GitHub health
and discovery workflows were already manually disabled when inspected. Preserve
that pre-existing state unless deliberately changing the deployment schedule.
CI remains enabled. A workflow file containing a cron schedule does not establish
that the workflow is enabled or that a particular run succeeded.

## Change the code with evidence

Start with one failing or incomplete source example. Identify whether the problem
is extraction, interpretation, persistence, freshness or a consumer assumption.
Changing a selector cannot repair a database update path that never writes that
field, and cleaning database values cannot stop a broken parser from adding more.

For a portal change, save a representative HTML fixture, isolate the primary
listing region, and test missing fields and unrelated-card contamination. Use
different bedroom, bathroom and toilet values in tests: equal fixtures concealed
the original first-widget defect. Include conflict, range and malformed cases.

For a rule change, add the example to the relevant pure assessor tests. Keep the
source wording, ambiguity and expected status visible. A simple alias belongs in
the taxonomy; a source-bound human decision belongs in the reviewed registry;
a feature is not a new property type. Rule bytes enter repair fingerprints, so
regenerate previews after changing interpretation code.

For persistence changes, use a disposable local PostgreSQL database. Test the
meaningful invariant: original values survive, before/after evidence is accurate,
stale source is rejected, failures roll back and retries/reversal respect ownership.
Do not rely only on a mock asserting that a SQL string was called.

```bash
# Point BOTH variables at a disposable local test database before pytest.
export TEST_DATABASE_URL='postgresql:///property_scraper_test?host=127.0.0.1'
DATABASE_URL="$TEST_DATABASE_URL" python -m pytest tests -q
```

CI uses Python 3.12 and PostgreSQL 16. Database fixtures apply migrations. Never
point them at production: some tests deliberately alter/drop schema objects.
Offline parser/assessor tests do not need production access. Use conventional,
incremental commits and PRs targeting `master`, then deploy reviewed merged code.

Migrations currently replay in filename order rather than using a checksummed
migration ledger. Older view introductions must preserve columns appended later;
011 and 014 contain guards for this. Test replay as well as a clean installation.
Installing schema alone does not backfill historical records or prove a rollout
finished. Avoid manually running an old preview against newly changed rules.

## Where to improve next

These are recommendations, not claims that the work is already implemented.

One existing collection-policy gap deserves explicit attention: normal discovery's
`BaseParser._robots_allowed` currently contains a bypass and returns true. The
controlled verification uses its own robots checks. Consolidate effective policy
checks across discovery, health and recovery before widening collection; do not
assume the method name proves that a gate is active.

1. **Measure field coverage continuously.** Track evidence-supported values,
   unresolved reasons, source age and verified outliers by portal and asset class.
   A rising row count is not a data-quality metric. Retain observed/attempt times
   separately from assessment time; an inaccessible page does not establish a
   removal, and a matching hash does not establish a recent fetch. Normal health
   selection requires feed absence: it is not a periodic census of every active URL.
   Choose a discovery/census schedule deliberately, and persist fetch-attempt and
   successful-observation times independently of interpretation changes.
   Alert on sudden parser coverage
   drops and selector drift, using genuinely different fixture values.
2. **Retain compact observation evidence.** Raw strings, source spans, extraction
   versions and timestamps make decisions reproducible. Add a bounded retention
   policy for compressed primary-page snapshots where worthwhile; avoid an endless
   pile of unlabelled HTML or repeated report copies on a nearly full disk.
   Keep an observation ID across quote, room, area and classification facts, so a
   study can align facts from the same page version rather than mixing a newer
   room count with an older retained quote.
3. **Introduce a real migration ledger.** Record a checksum and installation time
   once per migration, then update every local/cloud entry point consistently.
   Do not bolt a ledger onto just one runner while the others still replay SQL.
4. **Batch verified observations.** Network concurrency alone does not remove
   database round-trip costs. Use the guarded bulk room API for unchanged-source
   observations, preserve real before states and individual audits, and keep full
   source refreshes transactional. Bound retries, requests, time and concurrency.
5. **Cache fingerprints per frozen operation.** Current assessors repeatedly read
   rule/registry bytes. An immutable release can compute those once. Keep invalidation
   explicit so a long-lived process cannot silently apply changed rules.
6. **Treat physical-property matching as a separate model.** Start with candidate
   links using location, form/layout, source timing and appropriate image/address
   evidence. Keep uncertain links reversible. Never merge adverts merely because
   their titles, bedroom counts or neighbourhoods match; blocks and units complicate
   identity. Keep asking-price history separate from physical-property history.
7. **Expand area evidence carefully.** The area assessor now separates land, floor
   and unspecified claims from titles, descriptions and labelled primary fields.
   Next, extend portal fixtures and review held claims before supporting further
   wording or unit conventions. A price per sqm is not a property size. Never
   assume a universal sqm size for an unspecified plot.
8. **Profile storage and queries before adding infrastructure.** Keep one current
   listing store with indexed identities and append-only evidence. Audit/history
   retention needs a deliberate policy. Use EXPLAIN on actual consumer queries;
   add indexes or materialized exports when measurements justify them. Moving
   tables between schemas changes organization, not their physical storage cost.
9. **Make every monitoring surface honest about fallbacks.** The telemetry/dashboard
   path has legacy fallback/sample values. It is an operational display, not the
   research source of truth. Label missing/stale metrics explicitly before treating
   its cards as authoritative measurements. The database contract and dated reports
   are the evidence for this rollout.
10. **Keep operations understandable.** One deployment state, resumable run IDs,
    visible budgets and a short maintained handoff beat many competing cron jobs.
    Scope changes and unavailable evidence should produce explicit next actions,
    not quiet guesses or unexplained NULLs.

