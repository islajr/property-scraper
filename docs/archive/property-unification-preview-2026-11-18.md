# Unified property preview, 18 November 2026

Read-only production snapshot: 08:09:05 UTC. These are proposed results, not a
claim that classifications/counts/features have been applied to production.

| Measure | Listings |
| --- | ---: |
| Inventory scanned | 28,955 |
| Classified | 26,049 |
| Insufficient identity evidence | 2,127 |
| Ambiguous identity | 756 |
| Unsupported identity | 23 |
| Source-bound user review matches | 31 |
| At least one accepted count observation | 19,459 |
| Advertised feature claims | 17,316 |
| Detected/reviewed alternative offers | 6 |

Coverage is not an accuracy estimate. Offer detection is conservative and not
exhaustive. The 2,906 unresolved identities remain queryable with their status and
a queue action. All 31 reviewed examples obtain primary types; four retain
specific follow-up questions recorded in the current operations guide.

The production baseline contained 25,681 classified, 2,256 insufficient, 784
ambiguous, 32 unsupported and 202 legacy-unreviewed records, all on v1 or legacy.
The v3 proposal leaves no unreviewed legacy observations after a complete,
unchanged-source apply. Source changes during rollout require a fresh preview.

Report SHA-256:
`76bbd36d2ac7fed8c6d9f071dc925c15a229e88b2c2bc074c50b696f9dc9c137`.
Code SHA-256:
`7075eeac5b7dff6a5a1f5f03d3c3b884cd3bae39e14bae015c73bc53ee57e488`.

Private source backup SHA-256:
`18fd04300b00cbc70e6a104c1b5988615a505adea96e21f3f6c2f4282fe4e436`.
Original user-reviewed CSV SHA-256:
`9673341735e6d1cdeb69208883f24b8449c005fcfaa06e0a6e65104211ab2dd9`.
Detailed source/preview files remain in ignored private storage.

Migration 009 from merged master was installed successfully in production;
assessment and observation tables remained empty. New integration migrations
010/011 and the historical apply await the integration PR's merge and deployment.
No listing, price, description or lifecycle data was rewritten by this preparation.

The legacy `market.classify_property(title text, raw_type text, bedrooms integer)`
function still exists. Catalog inspection found no database dependents and no
market-schema property_type columns. This cannot discover dynamic external callers.
The integration provides a separate stable view; external consumers must adopt it.

Validation: the full disposable-database suite passed 636 tests. Subsequent targeted
checks for dedicated home-office features also passed. Reviewed cases are
regression examples rather than independently sampled ground truth.

The final attachment-modifier correction recognizes explicit wording such as
“four bedroom detached duplex”, recovering count evidence for 6,720 additional
listings compared with the initial same-day preview. Landmarks, out-of-range
quantities, ranges and mixed-layout guards remain enforced.

Final full-data rehearsal on an isolated local database processed all 28,955
listings in 58 atomic batches (298 seconds). All 28,955 protected source/pricing/
lifecycle rows were unchanged. The database held 28,955 classification audits,
28,955 count assessments, 35,254 observations and decisions, 28,955 feature
assessments and 28,955 durable receipts. Every listing had a current research
contract, including unresolved identities. Retrying the completed operation
attempted zero rows. The final read view reconciled one row per listing and all
35,254 quantity claims. This was a local rehearsal, not a production backfill.
