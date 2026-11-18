# Room-count audit and repair rehearsal — 18 November 2026

This report records the revised count-preserving policy and its production
**read-only preview**. The earlier proposal to clear unsupported existing numbers
was rejected and withdrawn: a parser defect does not prove an individual stored
number is wrong. The room repair has **not been applied to production**.
The current operating instructions are in
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
their supporting evidence needs checking. They must not be labelled incorrect
or cleared merely because they came through the affected parser.

Bounded live checks confirmed a PropertyPro primary widget showing four beds,
four baths and five toilets. A land listing had no room widgets despite its old
1234/123 values. A Private Property maisonette showed three bedrooms and an empty
bathroom widget; its saved bathroom value was three. Redirected pages were skipped.
These samples validate the mechanisms, not the accuracy of every listing.

## Production preview: what would change

The read-only snapshot was taken at **2026-11-18 13:20:01 UTC**. Normal scraper
activity may change later preview totals.

| Measure | Bedrooms | Bathrooms |
| --- | ---: | ---: |
| Listings scanned | 28,955 | 28,955 |
| Existing non-null numbers replaced or cleared | **0** | **0** |
| Previously empty fields filled from explicit evidence | 729 | 7 |
| Stored numbers with consistent supporting evidence (KNOWN) | 21,357 | 197 |
| Existing numbers retained as UNVERIFIED | 4,164 | 24,181 |
| UNKNOWN, with no stored number or supporting count | 1,750 | 2,939 |
| AMBIGUOUS | 9 | 0 |
| REVIEW_REQUIRED | 38 | 3 |
| MIXED_LAYOUT | 1 | 0 |
| NOT_APPLICABLE, with no stored number | 1,636 | 1,635 |

**Every existing non-null bedroom and bathroom number is preserved.** UNVERIFIED
means the retained number lacks sufficient consistent supporting evidence; it is
not a claim that the number is wrong. Missing evidence never authorizes a deletion.
The only numeric changes are fills of previously empty fields from explicit
evidence. These totals describe evidence coverage, not an accuracy estimate.
KNOWN means supported as advertised, not physically inspected. Basis still
distinguishes per-dwelling claims from counts attached to the advertised asset.

Stored numbers remain available in the main columns and the research view;
consumers choose whether to include UNVERIFIED values. Supported per-dwelling
fields require KNOWN status. `room_count_legacy` retains the first pre-repair
numbers, with immutable before/after evidence in existing fact history.
Candidate counts, stored counts, evidence status and storage action are separate.
The repair does not infer bathrooms from bedrooms, toilets, ensuite wording or a
typical layout. It does not rewrite prices or source text.

Future observations may correct an existing number only when a fresh,
unambiguous labelled primary metric supports the replacement. Missing, malformed,
conflicting, redirected or unavailable observations leave the stored number intact.

The preview is informational (`apply_compatible=false`) because production did
not yet have migration 012. Applying requires a fresh preview after that migration.
Private row-level artifacts remain outside Git under `.local/room-counts/`.

Preview provenance:

- Rules/repair fingerprint: `0655df91cc64e2a5adffaf3ec4f06a8f103643bf193453f8d70490fc6042434d`
- Preview SHA-256: `d2b69040f2a4323f8a9d19223c8b1ffc490a2924a44c669783e0e9bdc7dbf991`

## Full-data rehearsal

All 687 tests pass against disposable local PostgreSQL. They cover preservation
of plausible and unusual historic counts, missing new metrics, conflicting claims,
evidence-backed corrections, raw-source identity, atomic failures, stale previews,
reversal ownership, source freshness and recovery.

The revised full-data rehearsal completed in **260.6 seconds across 58 batches**
on a separate disposable copy of the earlier audit snapshot:

- No existing non-null bedroom or bathroom count changed.
- All 28,955 first pre-repair bedroom/bathroom pairs were retained in legacy data.
- All 28,955 listings had current room assessments and corresponding audit records.
- Every protected non-room field remained unchanged across all 28,955 listings.
- Retrying the completed operation attempted zero records.

That older source snapshot supplied 725 empty bedroom fills, compared with 729
in the fresher production preview. Both supplied 7 empty bathroom fills. Neither
changed an existing non-null number. Do not combine their other coverage totals.

The rehearsal report SHA-256 was
`574598c47568b800d7e2e09a4b864a1f5c74ee7683a43d65d5456b8379156f83`.
The local run ID was `d46ac67c-8510-43f6-b27c-355c7ab03f89`; it is not a
production operation. Older rehearsals of the withdrawn clearing policy are not
validation of this revised policy.

## Deployment and the remaining recovery work

Merge the reviewed PR into master before deployment. Pause writers, retain a
private backup, install 012, make and inspect a fresh preview, apply a small canary,
then use a new preview/run for the remaining inventory. Verify preservation,
coverage, zero changes to existing non-null counts, audit totals and completed retries before installing 013 to publish
`property-research-v2`. Resume writers from the merged code.

The repair itself is bounded and rehearsed. Recovering every missing room count
is a separate coverage task: many pages omit counts, have changed or are gone.
The primary-page recovery command checks identity and source agreement, respects
robot directives and coordinates traffic with health checks. Start with small
batches, inspect the reports, then continue from the saved cursor. Changed source
needs a full listing observation; conflicts need evidence review. Unavailable
pages retain their existing numbers with explicit evidence-quality markers.
The current assessment can be fresh while a particular retained number is
UNVERIFIED: assessment applicability is not verification of the number.

The broader architecture guide, schema usability work and extraction of sqm
measurements remain follow-up tasks after the room-count deployment.
