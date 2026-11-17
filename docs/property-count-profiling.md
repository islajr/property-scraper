# Saved property-count text: read-only profiling

This tool implements the profiling milestone following the count semantics
accepted on 17 November 2026 in [review PR #12](https://github.com/islajr/property-scraper/pull/12).
It introduces no count columns, facts, migration, apply command, or portal visits.
It is independent of the classification fixes in PR #13.
The [17 November aggregate profile](property-count-profile-2026-11-17.md)
records the production findings and their limits.

## Run and inspect

```bash
python -m scripts.profile_property_counts \
  --output .local/property-counts/profile.jsonl
```

The command uses DATABASE_URL from the environment or .env and starts a
server-enforced, read-only repeatable-read transaction. It selects primary titles
and descriptions, source/lifecycle identity, xmin, and the row's last-seen time.
Existing canonical types and numeric bedroom fields are not count inputs.
Connection errors suppress libpq details.

The private JSONL report contains one entry per listing, with source offsets,
literal text, normalized candidate quantities, context, flags, and relation
hints. The summary records the snapshot, profiler version/source fingerprint,
report checksum, counts, and portal/lifecycle coverage. Reports are replaced
atomically per file; check the report checksum before pairing a summary and
report. Output files have private temporary-file permissions. Keep detailed
listing evidence under the ignored .local directory, not in Git.

## What a result means

| Profile state | Meaning | Next action |
| --- | --- | --- |
| COUNT_CANDIDATES | A literal supported pattern matched; its role is not established | Review the pattern and contexts, then distinguish offered assets, contained units, bedrooms, or availability |
| POSSIBLE_CONFLICT | Exact quantities for a comparable entity differ between title and description | Check source wording, mixed layouts, and offer alternatives before declaring a contradiction |
| OFFER_ALTERNATIVES | Wording suggests per-unit/all-unit or individual/together options | Link count and price evidence to separate offer options, without duplicating the listing |
| NO_PATTERN_MATCH | None of the current patterns matched | Review missing patterns, saved evidence, applicability, and any truncation; do not infer absence or default one |

These four states partition listings. Entity and flag counts overlap. A listing
can contain building, flat, bedroom, and BQ counts in the same advert; mention
totals are not property totals. Title and description repetitions are retained
as separate evidence, not summed. A profile's requires_review flag concerns its
candidate/truncation output; it is not a worklist closure decision. No state
means a count has been independently verified or applied.

Patterns cover digits, common English numbers through ninety-nine, grouped
integers, ranges, lower bounds, basic bedroom shorthand, and bounded asset nouns
and modifiers. Source words and offsets are retained. Currency-prefixed amounts
are masked in place so a price joined to the next unit description cannot become
a count or range. Mixed-layout notation such as 4 × 3-bedroom flats produces
separate candidate quantities, not a derived twelve-bedroom fact.

Flags retain possible non-primary context, negation, BQ rooms, invalid zero asset
counts, bedroom shorthand, and range ambiguity. A hyphen can describe a range,
list numbering, or mixed layouts: never accept a range merely because it matches.
Property form, whole-building scope, counts of missing assets, and distribution
across buildings are never inferred from existing fields or these patterns.

## Limits and safe use

Titles stop at 2,000 characters, descriptions at 20,000, and reported candidates
at 100 per listing, prioritizing title evidence. Truncation is explicit. Only
basic offer-option wording is flagged; different layouts, stock availability,
agent inventories, irregular number spellings, or other phrases can require
additional review. Possible conflict detection is an initial grouping aid, not a
complete contradiction detector. No-match is not evidence that counts are absent.

The report is marked property_count_profile and apply_compatible=false. It is
not a classification backfill artifact, an accepted count dataset, or a replacement
for the research coverage denominator. Its source timestamp is the extraction
snapshot; last_seen_at is preserved as row metadata, not relabelled as a verified
count observation time.

## Next implementation milestone

Review representative count phrases, relation boundaries, flags, and gaps.
Then review the [storage design](property-count-storage-design.md), including
query examples and how proposed observations become accepted values. Additive
schema and extraction/apply behavior belong in a later focused PR against master,
after that review. The current profile writes no production data.
