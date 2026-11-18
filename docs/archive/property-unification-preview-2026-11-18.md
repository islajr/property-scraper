# Unified property preview, 18 November 2026

Read-only production snapshot: 07:58:36 UTC. These are proposed results, not a
claim that classifications/counts/features have been applied to production.

| Measure | Listings |
| --- | ---: |
| Inventory scanned | 28,955 |
| Classified | 26,049 |
| Insufficient identity evidence | 2,127 |
| Ambiguous identity | 756 |
| Unsupported identity | 23 |
| Source-bound user review matches | 31 |
| At least one accepted count observation | 12,739 |
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
`f17630e6c2e92bb9b553a544f0cfb7fd2c445bc6e34f6ceb006f517319947fde`.
Code SHA-256:
`76ece3a8b3e46ce44a5f4de734537cec0cf7f265e1ea25fe2871568eab8c5139`.

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

Validation: the full disposable-database suite passed 623 tests. Subsequent targeted
checks for dedicated home-office features also passed. Reviewed cases are
regression examples rather than independently sampled ground truth.
