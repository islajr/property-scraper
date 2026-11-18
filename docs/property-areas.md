# Understanding the size of a listing

A size is useful only when we know what it measures. “A house on 600 sqm” describes
land. “Floor area: 250 sqm” describes floor space. “500 sqm apartment” leaves that
role unclear, so we retain the claim without inventing a floor measurement.

The parser collects labelled primary area widgets. The assessor also reads titles
and descriptions. It converts sqm, sq.m, m², m2, square metres, square feet,
hectares and international acres. No fixed sqm-per-plot assumption is made.
`raw_floor_area` is reserved for an explicitly identified floor field. Generic
portal Size widgets use `raw_area_fields`, whose role can remain UNSPECIFIED.

Each claim includes its original text and unit, converted sqm, role, scope/basis,
approximate wording and reasons it may be held. Rates, ranges, bounds, ancillary
features, conflicting claims and unclear per-unit/shared-site sizes cannot silently
populate an asset-wide scalar. This is bounded text interpretation: unsupported
wording remains a follow-up task, not proof that a size was absent from the advert.

Existing non-null areas are preserved. Missing supported values can be filled.
The first prior values remain in `area_legacy`; every change is audited in the
existing `property_fact_assessments` table under `property-areas-v1`. Existing room,
quantity and feature audits remain independent. Only an existing legacy floor value equal to the old one-decimal sqft conversion
can use a rounding match; the exact converted claim remains
available. This does not certify the portal's physical measurements.

## Consumer queries

After migration 015, `research.properties` adds `supported_floor_area_sqm`,
`supported_land_area_sqm`, `floor_area_status`, `land_area_status`, `areas_current`
and `area_evidence`. Retained numbers remain in `stored_floor_area_sqm` and
`stored_land_area_sqm`. The older raw_data research contract retains its prefix.

`research.area_measurements` exposes individual claims. Always consult the final
field status before using one: two individually usable claims may conflict.
A matching source hash means applicability to saved text, not a recent visit or
an independent survey. Source or stored-value edits invalidate the old reader.

## Preview, apply and reverse

Apply schema migrations in order. Keep artifacts private under ignored `.local/`.
The preview uses a read-only repeatable-read transaction:

```bash
python -m scripts.repair_areas preview --output .local/areas/preview.jsonl
python -m scripts.repair_areas apply --report .local/areas/preview.jsonl \
  --run-id YOUR-UUID --ids 123,456 --max-records 2
```

The second command is also read-only. Inspect the summary, claims and proposed
values, then add `--apply` to write the same selection. Expand to a new reviewed
run without `--ids` for the full population, using at most 500 records per call.
Resume with the same run ID and report until `attempted` is zero. Receipts prevent
repeating completed records. The manifest binds target, artifact, rules and IDs;
row versions and recomputation protect concurrent changes. A new observation
requires a regenerated preview, not bypassing a concurrency receipt.

```bash
python -m scripts.repair_areas reverse --original-run-id YOUR-UUID \
  --run-id NEW-UUID --max-records 100
```

Reversal also defaults to read-only; add `--apply` only after reviewing eligibility.
It requires the exact latest assessment, original operation and unchanged row
version/values. Later edits are preserved. Starting a reversal prevents resuming
the original apply operation. These commands never fetch pages or send messages.
