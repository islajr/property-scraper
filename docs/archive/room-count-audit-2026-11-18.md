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

The latest read-only snapshot was taken at **2026-11-18 13:50:18 UTC**. Normal scraper
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

- Rules/repair fingerprint: `8e2e720e7f249aa79f171cc03490cc8a1115df4a1777466ee7916926b766bac9`
- Preview SHA-256: `fc5e5ecdfe02293b733fd1db9e31a08dabee6970483593e76436b509e56a1d6e`

## Explicit exceptional-value review

The latest preview identifies **1,831 distinct listings with review flags**.
Within that group, 1,406 have numeric/context exceptions at priority 0 or 1,
and 1,274 have at least one 100+ count. There are 837 bedroom fields and 1,274
bathroom fields at 100 or more; those groups overlap. No negative values were
found in this snapshot.

| Review trigger | Listings flagged |
| --- | ---: |
| 100+ room count | 1,274 |
| Possible concatenated digits (123/1234) | 1,274 |
| Positive room count on land | 430 |
| Stored/source conflict | 764 |
| Unusual room ratio on a residential unit advert | 340 |
| Unexplained zero | 54 |
| Count between 21 and 99 | 21 |

These counts overlap and are not confirmed-error totals. A hotel-wide quantity
needs different interpretation from bedrooms per flat. The flags preserve that
asset context and never authorize automatic correction by threshold alone.

The private full worksheet is
`.local/room-counts/preservation-preview-20261118T135018Z.review.csv` (27,148 rows,
including ordinary missing/unverified evidence as well as exceptions). Its SHA-256
is `3341920b3af43ecf5888fdf6a8ab5d636ac9400aa6eddafe435b86ca250445c0`.
Focused editable copies are under `.local/room-counts/review/`:

- `exceptional-room-counts-2026-11-18.csv`: 1,406 rows, including 1,331 active listings.
- `100-plus-room-counts-2026-11-18.csv`: 1,274 rows, including 1,216 active listings.

Each row contains the listing link, stored values, candidate values, field-specific
statuses, asset context, specific flags and the next verification action. Most
ordinary recovery should be automated; manual review is for exceptions that
source observations cannot resolve, not every row of the full worksheet.

## What dependent projects can already use

Among **18,448 active residential listings**, saved evidence supports 15,659
bedroom claims (**84.9%**) and 169 bathroom claims (**0.9%**). These are coverage
figures, not independently measured accuracy. Retained unverified numbers remain
available separately. A bedroom analysis need not discard a supported bedroom
because bathroom evidence is missing. Bathroom-dependent work still needs the
recovery pass; the low bathroom coverage is unfinished work, not a satisfactory
final state for that use case.

## Read-only recovery pilot

A targeted pilot selected eight recent exceptional records and up to eight
ordinary unverified records per portal, yielding 32 visits. It was purposive,
not a random accuracy sample. All visits respected the recovery traffic guard
and robot directives. No production writes were made.

| Outcome | Listings |
| --- | ---: |
| Matching saved source, usable supported room evidence | 17 |
| Matching saved source, still no usable room count | 8 |
| Changed source requiring a full listing observation | 7 |

The 17 supported observations confirmed the **existing bathroom values without
changing them**; all 17 would move from UNVERIFIED to KNOWN. One bedroom field
would also gain support. No corrections or missing-field fills were proposed by
this pilot. It demonstrates an actual route to reducing uncertainty without
discarding legitimate numbers, but does not establish a recovery percentage for
the remaining database.

The full private report is
`.local/room-counts/recovery-pilot-20261118T135315Z.json`; its companion selection
file records the worksheet and chosen records. These are proposed assessments,
not applied production improvements. The pilot confirmed 8 bathroom counts on
Private Property, 8 on Nigeria Property Centre and 1 on PropertyPro. Seven
PropertyPro records needed a full source refresh; those are follow-up candidates,
not evidence that their room values are wrong or permanently unrecoverable.

## Full-data rehearsal

All 696 tests pass against disposable local PostgreSQL. They cover preservation
of plausible and unusual historic counts, missing new metrics, conflicting claims,
evidence-backed corrections, raw-source identity, atomic failures, stale previews,
reversal ownership, source freshness, explicit outlier flags, worksheet contents,
and recovery of missing bedrooms even when bathrooms already have support.

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

That preservation rehearsal predates the latest diagnostic flags and worksheet
metadata. It remains the preservation baseline; the latest additions were checked
with the full 696-test suite and the fresh read-only production preview above.

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

After merge, verification is part of completion: process active exceptional values
first, then source conflicts and ordinary unverified fields in bounded automated
batches. Route changed-source records through full identity-checked observations;
do not depend on the ordinary health selection eventually including every row,
since that selection is restricted by cooldown and missed-run rules. Reconcile
supported counts and outstanding actions after each pass by portal and field.
Do not call the bathroom cleanup finished merely because every row has a marker.

The broader architecture guide, schema usability work and extraction of sqm
measurements remain follow-up tasks after the room-count deployment.
