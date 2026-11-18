# Room-count audit and repair rehearsal — 18 November 2026

This report records a production **read-only preview** and a repair rehearsal on
a disposable local database. The room repair has **not been applied to
production**. The current operating instructions are in
[property counts](../property-counts.md#bedrooms-and-bathrooms-evidence-backed-current-fields).

## What went wrong

PropertyPro and Private Property used the same first metric selector for both
bedrooms and bathrooms. Identical fixture counts concealed the mistake. Some
page text also combined separate digits into values such as 1234 and 123. The
generic integer parser accepted unrelated numbers, and update paths left old
numeric room fields untouched even when a listing was observed again.

The initial 28,955-row audit found 834 PropertyPro bedroom values of 1234 and
1,274 bathroom values of 123. All 7,024 populated Private Property bathroom
values equalled their bedroom values. Equality alone does not prove an individual
count wrong: a property can have three bedrooms and three bathrooms. It does mean
the affected fields cannot be certified from the old parser output alone.

Bounded live checks confirmed a PropertyPro primary widget showing four beds,
four baths and five toilets. A land listing had no room widgets despite its old
1234/123 values. A Private Property maisonette showed three bedrooms and an empty
bathroom widget; its saved bathroom value was three. Redirected pages were skipped.
These samples validate the mechanisms, not the accuracy of every listing.

## Production preview: what would change

The read-only snapshot was taken at **2026-11-18 12:29:10 UTC**. Normal scraper
activity may change later preview totals.

| Measure | Bedrooms | Bathrooms |
| --- | ---: | ---: |
| Listings scanned | 28,955 | 28,955 |
| Numeric values that would change | 4,893 | 24,188 |
| Supported scalar claims (KNOWN) | 21,986 | 242 |
| UNKNOWN | 4,565 | 26,578 |
| AMBIGUOUS | 102 | 2 |
| REVIEW_REQUIRED | 212 | 44 |
| MIXED_LAYOUT | 1 | 0 |
| NOT_APPLICABLE | 2,089 | 2,089 |

**Most bathroom changes replace unsupported numbers with NULL.** NULL means
missing evidence, not no bathroom. These totals are evidence coverage, not an
accuracy score or a claim that the other properties lack bathrooms. KNOWN means
supported as advertised; the basis still distinguishes per-dwelling counts from
counts stated for an advertised asset.

The repair preserves the first pre-repair numbers in `room_count_legacy`, exposes
them through the research view and records immutable before/after evidence in
the existing fact history. It does not infer bathrooms from bedrooms, toilets,
ensuite wording or a typical layout. It does not rewrite prices or source text.

The preview is informational (`apply_compatible=false`) because production did
not yet have migration 012. Applying requires a fresh preview after that migration.
Private row-level artifacts remain outside Git under `.local/room-counts/`.

Preview provenance:

- Rules/repair fingerprint: `4e763b035033309d0886e43eeb614436632691c00f76e6746f1ff3fa90e22c2e`
- Preview SHA-256: `0b3ad766769b3797a05a6cc9a6eaea3a53e0be7c15ae98194b18c11e0888e744`

## Full-data rehearsal

The disposable database was populated from the earlier production audit snapshot,
then migrated and repaired using the same rule fingerprint. Its source snapshot
differs from the production preview above: it had 22,022 supported bedroom counts
and 4,844 numeric bedroom changes. Do not combine those coverage totals.

The complete rehearsal finished in 247.2 seconds across 58 bounded batches:

- All 28,955 listings had current room assessments and corresponding audit records.
- All 28,955 original bedroom/bathroom pairs were retained.
- Every protected non-room field remained unchanged across all 28,955 listings.
- Retrying the completed operation attempted zero records.

The rehearsal report SHA-256 was
`4d1bb1b691698bc321ea21f7eedaa454fb23334ca13bd4e4baf3565e94da0cec`.
The local run ID was `5529ac30-327a-4bcc-97af-ce96724caff6`; it is not a
production operation. Database integration tests separately cover source conflicts,
atomic failures, stale previews, reversal ownership, source freshness and recovery.

## Deployment and the remaining recovery work

Merge the reviewed PR into master before deployment. Pause writers, retain a
private backup, install 012, make and inspect a fresh preview, apply a small canary,
then use a new preview/run for the remaining inventory. Verify preservation,
coverage, audit totals and completed retries before installing 013 to publish
`property-research-v2`. Resume writers from the merged code.

The repair itself is bounded and rehearsed. Recovering every missing room count
is a separate coverage task: many pages omit counts, have changed or are gone.
The primary-page recovery command checks identity and source agreement, respects
robot directives and coordinates traffic with health checks. Start with small
batches, inspect the reports, then continue from the saved cursor. Changed source
needs a full listing observation; conflicts need evidence review. Unavailable
pages retain explicit unknown markers and their original values for comparison.

The broader architecture guide, schema usability work and extraction of sqm
measurements remain follow-up tasks after the room-count deployment.
