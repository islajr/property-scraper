# Property classification

The shared classifier implements `property-types-v3` and the
[39-code vocabulary](property-type-taxonomy.md). Unknown portal text cannot create
new canonical codes. For consumers and deployment, use the
[unified contract and operations guide](property-unification.md).

## Decisions and evidence

Every observation records type, category, family, attachment, asset scope,
advertised land use, raw label/source, status, matched evidence, rule version and
time. Existing numeric bedrooms, transaction purpose, pricing and lifecycle
fields remain separate. Historic canonical labels are never supporting inputs.

| Evidence | Result |
| --- | --- |
| Semi-detached label and duplex title | SEMI_DETACHED_DUPLEX |
| Generic duplex | DUPLEX; attachment unknown |
| Explicit mini-flat in an apartment category | MINI_FLAT |
| Detached and terraced descriptors on the same duplex | DUPLEX; attachment conflict retained |
| Commercial label and explicit land title | LAND with advertised commercial use |
| Bungalow with a terrace amenity | BUNGALOW; terrace does not establish attachment |
| Contradictory block/individual-apartment claims | AMBIGUOUS unless a source-bound review resolves that snapshot |
| Gas plant, hostel or event hall | GAS_PLANT, HOSTEL or EVENT_VENUE |
| Bedrooms or rental purpose without a form | INSUFFICIENT_EVIDENCE |

A broad HOUSE does not become a duplex because it has four bedrooms. A commercial
category is not verified legal zoning. A default UNIT facet is not a numeric
count of one or certification of the price basis.

Specific phrases consume their own spans; incompatible assets remain conflicting
candidates. Broad compatible forms can be refined. Rules exclude amenities,
nearby landmarks, alternative uses and agent inventories. Description recovery
uses bounded leading identity statements and cannot generally override a
specific contradictory title or portal label. Missing historical labels are not
fabricated from old canonical values, descriptions or URL slugs.

The inherited v2 corrections recognize bounded Massionette and Roomself spelling
variants; bedroom/ensuite wording does not create extra ROOM assets. Corroborated
home offices and private cinemas remain ancillary. Independently offered offices,
cinemas and rooms remain primary candidates. The separate feature assessor saves
advertised amenities without increasing bedroom or asset quantities.

V3 adds the three specialist types and source-bound review decisions. The
[original review notes](archive/property-type-review-2026-11-14.csv) are interpreted
in `scraper/property_reviews.json`. Each decision is bound to portal identity and
the exact saved raw label/title/description hash. New source evidence expires the
override. Evidence records the case, date, original note and outstanding questions.
The registry is not a blanket rule that every similarly worded advert is the same
asset or that every image has been inspected by this program.

## Storage and ongoing observations

Migrations 006 and 007 supply metadata, vocabulary, immutable classification
history and classification-only operation receipts. Migration 008 preserves v1
and registers the unchanged v2 vocabulary. Migration 010 registers v3 with 39
codes; 011 supplies the unified consumer views. Apply migrations in order before
new writers. Rerunning a migration does not reclassify existing listings.

Discovery inserts, updates, relistings and identity-matched primary health-check
observations write classifications with their existing transactions. A changed
decision gets an immutable before/after audit; identical decisions preserve the
original decision time. Old checkpoints are recomputed when their classifier
version differs. Source-only prices and legacy callers do not invent raw evidence.
Count and feature assessments share the observation transaction. Failures roll
back all related changes.

For historical data, use the unified bounded preview/apply/reversal commands in
the [operations guide](property-unification.md). The older classification-only
[backfill guide](property-classification-backfill.md) remains for its original
operation receipts and reversals; it does not reverse unified operations.

## Compatibility and verification

Consumers should use `raw_data.property_research_current`, explicitly inspect
status/freshness, and retain unresolved rows in coverage denominators. Clients
must tolerate all supported codes and NULL with a reason. Pin a version for
reproducible studies. A supported type alone does not make prices comparable.

This repository does not replace an external `market.classify_property`, rebuild
external market snapshots or update other projects' enum definitions. Move those
consumers to the unified view or a documented adapter before relying on them.

Tests cover every canonical code; bounded aliases, primary conflicts and context;
source-bound review expiry; SQL vocabulary/status coherence; migration reruns;
transaction rollback; discovery/relisting/health checks; and frozen, resumable
backfills with safe reversal. Integration tests require a disposable explicit
TEST_DATABASE_URL and never use production as a test fixture. Reviewed examples
are regression cases, not an accuracy estimate for the full inventory.

Historical observations remain in the dated [audit](property-type-audit-2026-11-13.md),
[first preview](property-type-preview-2026-11-13.md), and
[v2 context preview](property-type-context-v2-2026-11-16.md).
