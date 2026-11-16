# Property classification: clearing unresolved cases

The user accepted the explicit scope rules on 16 November 2026, with unresolved
cases tolerated initially only if there are actionable steps to clear them.
The [joint review worksheet](property-type-review-2026-11-14.md) records that
decision. This plan turns unknown classifications into work with a next action.

## Starting inventory

A private, editable resolution backlog was prepared from the saved **14 November
2026, 04:31:28 UTC** production snapshot. It has one OPEN entry for each of the
3,298 non-CLASSIFIED listings: 3,070 with NULL types and 228 held legacy rows.
This is a dated baseline, not a new live database count. The classified comparison
examples, including scope errors, remain an additional review stream.

| Initial route | Listings | Next action |
| --- | ---: | --- |
| Spelling/alias review | 84 | Compare the advertised wording with the saved description; propose bounded aliases and counterexamples |
| Context review | 108 | Separate bedroom wording, home offices, and private cinemas from independently offered assets |
| Scope review | 228 | Find explicit unit, bundle, or whole-building evidence; route dual offers to representation review |
| Definition review | 413 | Examine competing candidates and settle the primary asset or identify genuinely separate offers |
| Vocabulary review | 19 | Confirm unfamiliar terms name the offered asset; propose definitions before adding codes |
| Saved-evidence review | 2,446 | Read the saved description for an identifying statement missed by the current rules; state the missing evidence question when none is available |
| **Total** | **3,298** | |

These are mutually exclusive initial routing groups, not approved classifications
or recovery forecasts. In particular, UNSUPPORTED rows mentioning a cinema are
routed to context review first; not all unsupported results need a new type.
Reassign a route when evidence warrants it and retain the original reason.

The first batch comprises the 420 spelling, context, and held scope cases.
Cases can be worked in parallel by topic without waiting for that entire batch
to close. Codex prepares evidence, rules, and previews; the user settles domain
definitions and disputed interpretations. These are proposed responsibility
roles, not assignments to an external service or scheduled background workers.

The private export is under the dated review directory in
`.local/property-types/`, as `resolution-backlog.csv`, with counts and checksums
in `resolution-backlog-summary.json`. It is ignored by Git. Only this aggregate
plan and the selected joint review examples belong in the documentation PR.

## Required information for every open case

Each entry records listing ID and portal URL, snapshot time and row version,
current classification, reason/route, priority, responsible role, workflow state,
next action, closure criterion, attempt count, evidence question, next review
stage, and resolution reference. Each route starts with an explicit evidence
question; narrow it to the missing fact as the case is investigated. Resolution
references are filled only after the relevant action. Initial entries are OPEN,
not already investigated or scheduled.

Use these working states in the backlog, independently of classification status:

| State | Required next action |
| --- | --- |
| OPEN | Examine saved evidence and record the specific interpretation or missing fact |
| NEEDS_EVIDENCE | State exactly what the primary page must establish, and queue a bounded identity-checked revisit |
| NEEDS_DEFINITION | Bring the competing interpretations and examples to the next joint review |
| NEEDS_MODEL | Record known offer options or asset structure that the current fields cannot represent; propose the representation |
| READY_FOR_PREVIEW | Test the approved interpretation and inspect its effect across all listings |
| READY_FOR_APPLY | Bind the reviewed preview and selection to an audited backfill run |
| RESOLVED | Link the applied decision, evidence, rule version, and audit receipt |
| BLOCKED_SOURCE_UNAVAILABLE | Record failed evidence attempts, the source condition, and the next review action; keep the case visible |

Reassignment is not resolution. A rule proposal, an attempted fetch, or a
CLASSIFIED value alone does not close a case with an outstanding scope question.
If a type is established before its scope, track that scope question separately
instead of withholding the supported type or calling the entire case complete.

## Resolution sequence

1. **Use the evidence already held.** Review title, raw portal label, description,
   and saved candidate matches together. Retrieve the full saved database
   description if the local 6,000-character excerpt was truncated. Record an exact
   identifying excerpt. Do not treat a previous canonical value as primary proof.
2. **Fix recurring causes in groups.** Take accepted spelling, context, and scope
   decisions into regression cases, including counterexamples. Preview changed
   type, status, and scope across the full inventory, including CLASSIFIED rows.
   Keep the remaining questions and cases visible in the report.
3. **Gather missing evidence deliberately.** Queue only the cases whose question
   the saved record cannot answer. A separate bounded primary-page operation must
   check listing identity, redirects, and evidence freshness. A current visit is
   new evidence: record its time without rewriting historical observation dates,
   prices, or lifecycle events. Removed pages that cannot be recovered stay in
   the blocked-source bucket with their attempted actions recorded.
4. **Represent known alternatives.** If both per-unit and bundle options are
   explicit, preserve their distinct scope and pricing evidence. Design an offer
   representation and consumer counting rules; avoid duplicating one advert into
   apparently independent properties. No new offer schema is approved here.
5. **Apply and reconcile.** Use a fresh reviewed preview and the existing bounded,
   resumable, audited backfill. Match outcomes back to backlog IDs. Close only the
   questions actually answered, and preserve newer observations if a row changes.

## Progress and closure

After every reviewed or applied batch, report the starting and ending backlog,
resolved IDs, new entries, reassigned cases, blocked cases, and oldest outstanding
review stage. Break down the remaining work by reason and portal. Refresh the
inventory before implementation and reconcile newly observed or reclassified rows;
do not replace this dated baseline silently or lose prior notes.

Report type coverage and scope coverage separately. Keep blocked and unresolved
records in the research coverage denominator. The objective is to clear every
recoverable case and give each remaining case a documented evidence gap and next
action; the plan does not promise that a disappeared listing can always be
reconstructed.

The local CSV is an initial worklist, not a live queue or automation. A durable
queue, automatic retry scheduling, new offer fields, classification fixes, and
production writes require implementation PRs against master. This documentation
change introduces none of those operations.
