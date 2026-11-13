# Property classification preview: 13 November 2026

The `property-types-v1` classifier was run across the full stored inventory in a
PostgreSQL-enforced read-only, repeatable-read transaction. The snapshot began
at **2026-11-13 10:06:43 UTC** and included **28,102 listings**, both active and
removed, from all three enabled portals. No migrations, classification updates,
or portal visits were performed against production.

These are proposed rule-based decisions from saved evidence, not a completed
backfill or a measured accuracy rate. The [rollout guide](property-types.md)
describes the classifier, limitations, preview command, and next migration steps.

## Proposed states

| Proposed state | Listings |
| --- | ---: |
| `CLASSIFIED` | 25,002 |
| `INSUFFICIENT_EVIDENCE` | 2,613 |
| `AMBIGUOUS` | 454 |
| `UNSUPPORTED` | 33 |
| Total | 28,102 |

The classifier finds supported types for 89.0% of this inventory. That is
coverage, not accuracy. The remaining 3,100 listings remain explicitly unresolved.
All 28,102 historic raw portal labels were unavailable in stored data; the
preview did not fabricate them from previous classifications. It used saved
titles and conservative description recovery instead.

## Coverage by portal and lifecycle state

| Portal | Lifecycle | Classified | Insufficient evidence | Ambiguous | Unsupported |
| --- | --- | ---: | ---: | ---: | ---: |
| NigeriaPropertyCentre | Active | 7,691 | 328 | 107 | 3 |
| NigeriaPropertyCentre | Removed | 2,656 | 41 | 5 | 2 |
| PrivateProperty | Active | 5,974 | 866 | 137 | 10 |
| PrivateProperty | Removed | 1,072 | 140 | 32 | 1 |
| PropertyPro | Active | 6,348 | 1,058 | 156 | 17 |
| PropertyPro | Removed | 1,261 | 180 | 17 | 0 |

## Transitions worth reviewing

13,125 stored type values would change, including transitions to NULL when
evidence is unresolved. 14,977 would keep their existing type value. Every row
would receive a new classification decision and provenance, since historic
classifications have not been reviewed under this version.

Selected proposed transitions into supported types:

| Previous type | Proposed type | Listings |
| --- | --- | ---: |
| `FLAT_APARTMENT` | `MINI_FLAT` | 1,352 |
| `DETACHED_DUPLEX` | `SEMI_DETACHED_DUPLEX` | 1,193 |
| `DETACHED_DUPLEX` | `DUPLEX` | 1,094 |
| `DETACHED_DUPLEX` | `TERRACED_DUPLEX` | 958 |
| `FLAT_APARTMENT` | `STUDIO` | 337 |

These counts are candidates for review, not an assertion that every prior value
was incorrect. A valid type can become unresolved when its original supporting
portal label was not retained and the surviving text cannot establish it.

The review also identified context traps that now have regression coverage:
“bungalow W/Terrace” retains unknown attachment, a mixed-use development
opportunity does not establish a built asset, and “bed rooms” in a description
does not establish an individual room listing.

## Artifacts and verification

The detailed JSONL and summary are local runtime artifacts, excluded from Git:

- `.local/property-types/preview-v1.jsonl`
- `.local/property-types/preview-v1.summary.json`

The report's SHA256 was verified against the summary:

```text
75c9a1e62c87988e0418190cbdba6106cbdf25109757cd46cbfb4f36c19886d6
```

The classifier source used by that run has SHA256:

```text
0baa7241570573be92bda57d8c983e117a78e6c1ddd7f29f1e32b3628ed7d7e6
```

The report's row count, status totals, type/status coherence, and raw-label
absence were checked independently after generation. Local validation passed
**449 tests** against disposable PostgreSQL, including migration reruns,
constraints, audit history, rollback, relisting, health-check corrections,
checkpoint compatibility, and pre-migration read-only preview. The 32 real-title
regression examples are evidence review cases rather than a random evaluation
sample.

Before any production backfill, review transitions and unresolved examples with
their full saved evidence, check downstream callers, and implement a separate
audited apply/reversal path with row-version checks and resume. Do not apply this
report as a blind mass replacement or treat today's classification as the type
known at a historic transaction date.
