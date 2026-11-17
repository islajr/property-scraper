# Reading guide: property data review

The review files are here so the user can understand the evidence, challenge the
definitions, and see what would change before implementation or production work.
Reviewing representative cases together supplements reading the plan; it does
not replace it.

## Read in this order

1. [Joint review worksheet](property-type-review-2026-11-14.md): the accepted
   definitions, pending decisions, and 31 saved listing examples. Each example
   shows the current result, evidence, proposed interpretation, and rationale.
   The [CSV](property-type-review-2026-11-14.csv) records the same decisions in an
   editable format; it is not the full backlog.
2. [Resolution plan](property-type-resolution-plan.md): how unresolved records
   move from evidence review through previews to audited corrections. It explains
   responsibilities, next actions, closure criteria, and progress reporting.
3. [Structured features proposal](property-features-proposal.md): how clues in
   titles and descriptions could become useful attributes without mixing them
   into property types. This design is still open for review.
4. [Property counts proposal](property-counts-proposal.md): how to distinguish
   assets offered, dwelling units within a building, and bedrooms per dwelling.
   Read this before agreeing to numeric fields or extraction rules.
5. [Accepted taxonomy](property-type-taxonomy.md) and
   [implementation guide](property-types.md): the current 36 codes, metadata,
   evidence rules, storage, and consumer contract. Consult these for detail.

The older [13 November preview](property-type-preview-2026-11-13.md) describes a
historic classifier preview. It is neither the current review worksheet nor a
live worklist. The private `resolution-backlog.csv` under the dated
`.local/property-types/` review directory has all 3,298 unresolved/held records
from the 14 November snapshot. It is a dated starting inventory, not a live queue.

## What is accepted and what changes next

The user has accepted the five apartment/room definitions, explicit asset scopes,
and six spelling/context interpretations. Unknown scope is accepted initially
only with a tracked next action. The worksheet records exactly which cases and
parts of cases have been accepted; other proposals remain pending.

The classifier implementation in [draft PR #13](https://github.com/islajr/property-scraper/pull/13)
addresses the accepted spelling/context cases against master: bounded
maisonette/self-contained aliases, bedroom and ensuite wording, and home
office/private cinema context. It includes contrasting cases that retain
independently offered assets, a new rule
version, and a read-only database preview. Bedroom counts are not invented
from amenities or changed by those classification rules.

Its final preview compared v1 and v2 on 28,955 listings on 16 November: 154
additional classifications are proposed, and four previously supported results
expose unresolved questions. All 534 tests passed. The PR contains the aggregate
report and deployment order; the changes have not been applied to production.
The older worklist must be reconciled with the newer inventory before backfill.

Both PRs remain unmerged for review. PR #12 records the design discussion; PR #13
implements the already agreed classification corrections. Counts and structured
features are not implemented by either PR and do not need to be folded into the
classification fix. Their next step is semantic review and a read-only profile,
followed by a separate implementation proposal against master.

Structured feature fields, offer alternatives, new type codes, pending aliases,
backlog automation, and downstream consumer changes require separate reviewed
design and implementation. The documentation PR itself changes no production
records. An implementation PR must state the final behavior and preview results;
the production backfill remains a separate audited operation.

## What to look for while reading

- Does the definition match the asset the advert is actually offering?
- Does the quoted wording support the proposed type, scope, count, or feature?
- Is the wording describing the main property, an amenity, a landmark, or a
  different offer on the same page?
- Is a missing fact still represented as unknown, with a concrete next action?
- Are the proposed changes preserving evidence, historical observations, and
  compatibility for research and other consumers?

The user can comment on a definition, cite a case ID, or edit a review decision.
Codex prepares evidence, implementation, tests, previews, and operational reports;
domain decisions and review of the resulting behavior remain collaborative.
