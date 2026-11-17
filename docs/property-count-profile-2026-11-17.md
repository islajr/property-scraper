# Property-count profile: 17 November 2026

Status: completed read-only saved-text profile. The count semantics were accepted
in [review PR #12](https://github.com/islajr/property-scraper/pull/12); the
[profiler](property-count-profiling.md) gathers candidate evidence, not accepted
facts. There were no production writes, migrations, or listing-portal requests.


Correction: this refreshed profile fixes a numeric-boundary bug that could split
12 bedrooms into a false one-unit/two-bedroom candidate. The earlier preliminary
unit/building-clue total of 1,794 is superseded by 1,744; no counts were applied.

## Snapshot and outcome

Snapshot: **2026-11-17 22:38:09.714111+00:00**, or 23:38:09 WAT on 17 November.
The complete inventory contained **28,955 listings**, including
active and removed listings across the three enabled portals. PostgreSQL enforced
a read-only repeatable-read transaction. Existing numeric bedroom fields and
canonical property types were not used as count inputs.

| Disjoint listing profile state | Listings |
| --- | ---: |
| Quantity candidates, without an alternative/conflict state | 22,913 |
| Possible title/description quantity conflict | 301 |
| Basic offer-alternative wording matched | 3 |
| No supported count pattern matched | 5,738 |
| **Total** | **28,955** |

There were **50,833 literal candidate mentions** across
**23,217 listings**. Repetitions between title and description
are independent evidence entries, not additional assets.

Useful distinctions within that evidence:

- **1,744 listings** have building, dwelling-unit, or unspecified-unit mentions.
- **20,669 listings** have only bedroom or bedroom-shorthand mentions.
- **2,548 listings** have other count entities, including rooms that may be BQ amenities.
- **13 listings** have a range or lower-bound candidate.
- **2,518 listings** have at least one context, shorthand, or numeric review flag.
- **3 listings** hit an input/candidate limit and need fuller inspection.

These metrics overlap. In particular, 23,217 listings with number clues does not
mean 23,217 unit counts can be filled. Most of the evidence describes bedrooms.
No-match does not prove a count is absent; it can reflect wording outside the
current patterns. The three simple offer-alternative hints are not a complete
inventory of adverts offering different units, layouts, or prices.

## Count entities found

| Candidate entity | Listings with at least one mention |
| --- | ---: |
| BEDROOM | 22,576 |
| BEDROOM_SHORTHAND | 1,911 |
| BUILDING | 38 |
| DWELLING_UNIT | 312 |
| ROOM | 897 |
| UNSPECIFIED_UNIT | 1,496 |

Entity counts overlap. A listing can mention two buildings, fourteen flats, and
several bedroom layouts. ROOM also includes potential ancillary accommodation;
none of these counts is a validated count of assets offered for sale or rent.

## Examples supporting the storage design

| Listing | Saved quantity evidence | Required distinction |
| --- | --- | --- |
| 69 | 5 units; the client must take them at once | A bundle count, with the particular dwelling form established separately |
| 6632 | 4 units; 3 bedrooms; a block of 4 flats | Contained dwellings versus bedrooms; do not manufacture a numeric building count from a type code |
| 15921 | 4 units; 2 bedrooms; per-unit and all-units prices | One listing with distinct offer alternatives, not duplicate property records |
| 22969 | Block of 4 flats, 3 bedrooms each | Four contained units and three bedrooms per unit; no unlabelled twelve-bedroom total |
| 24456 | 2 separate buildings; 14 units; 4 × 3-bedroom, 4 × 2-bedroom, 6 × mini-flat | Portfolio totals, parent structure, and a mixed-layout breakdown, without assigning seven units to each building |

Currency amounts can be joined to the next unit description in saved text.
The profiler masks those amounts before matching while preserving source offsets.
Likewise, mixed-layout multiplication signs create separate quantity candidates,
not calculated bedroom totals. Both boundaries have regression examples.

## What this changes in the plan

A single numeric unit_count column would be inadequate for these observations.
The [storage design for review](property-count-storage-design.md) proposes
assessment records, child count observations, and append-only acceptance history.
It separates quantity, entity, relationship, parent/offer, source evidence, and
review state. It also illustrates consumer queries that exclude unaccepted claims.
No table names, fields, migration, or apply behavior have been approved by this
profile. No regex match has been promoted to a production fact.

The next review should settle entity/relationship assignment rules on samples
of the 1,744 building/unit cases, while retaining mixed offers and source conflicts
as separate work. Missing-count actions must distinguish unsupported wording,
missing source evidence, and cases where that count is not applicable. Review
patterns in batches; this is not a requirement to manually inspect every listing.

## Validation and artifacts

**522 tests passed**, including an explicitly disposable PostgreSQL integration
check that the profile transaction rejects writes and leaves stored listing rows
unchanged. The check also proves that a stored bedroom value of 1234 does not
supply count candidates. Other cases cover ranges, lower bounds, source offsets,
compound numbers, money spillover, mixed layouts, alternatives, non-primary
context, truncation, and credential-safe connection failures.

Detailed reports remain private under the ignored .local/property-counts tree.
The report has one row per listing; IDs, totals, checksum, and selected example
outputs were checked. The summary marks it apply_compatible=false. It cannot be
used as a classification backfill artifact or an accepted research dataset.

Report SHA-256: `e150711a2adcb638b15fb395e57608996d2dd7d2ebf9bf4886ae7c21b62b7097`.
Profiler SHA-256: `8bffc50e8ee94e95800a1e982faf0d907d21382554d1fd6b8b33df5cf75cf6b9`.
