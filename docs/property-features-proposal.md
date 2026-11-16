# Structured property features: proposal for review

Status: design proposal. No feature schema, extraction worker, or production
update is introduced by this document. The user identified that agents often
leave useful clues in listing titles and descriptions even when they do not use
consistent terminology. Preserve those clues and make their meaning inspectable.

## Keep separate facts separate

| Dimension | Example | Evidence boundary |
| --- | --- | --- |
| Property form | SEMI_DETACHED_DUPLEX | Identifies the offered asset |
| Asset scope | One unit, several units together, whole building | Describes what the offer includes |
| Bedroom count | Three bedrooms | Requires an explicit count; all rooms ensuite supplies no count |
| Unit count | Four flats | Does not establish bedrooms per flat or a whole-building sale |
| Amenities | Home office, private cinema, BQ, pool, gym | Must belong to the offered property rather than a nearby landmark |
| Layout and fittings | Separate living room, open-plan kitchen, ensuite rooms | Preserve the stated layout; do not assume it from bedroom count alone |
| Marketing claims | Luxury, massive, executive | Keep as source claims; they are not measured quality or area |
| Offer alternatives | Per-unit price and all-units price | Preserve alternatives without duplicating the property inventory |

A home office is commonly a room within a home, but that observation does not
justify increasing bedroom count or assigning a separate ROOM property type.
A pool advertised as an estate facility is different from a private pool in
the unit. Furnished does not establish which appliances are included.

## Evidence-bearing attributes

Each extracted attribute should preserve its key and normalized value, the exact
source wording, source field, observation time, extraction rule version, and
relation to the asset (private, shared, ancillary, or unknown). Counts and units
must be explicit. Retain multiple evidence items when sources disagree.

For example, the proposed representation of “4-bedroom semi-detached duplex
with a home office and private cinema” would contain:

```json
{
  "property_type": "SEMI_DETACHED_DUPLEX",
  "bedrooms": {"value": 4, "evidence": "4-bedroom"},
  "features": [
    {"key": "home_office", "value": true, "evidence": "home office"},
    {"key": "cinema", "value": true, "relation": "private", "evidence": "private cinema"}
  ]
}
```

This is an illustration, not the final API or storage format. The final format
needs provenance, conflict handling, and unknown states as described above.
Keep stated facts distinct from inferred candidates. A supported alias can
normalize explicit text; an uncertain layout inference remains a candidate for
review rather than silently becoming an established attribute. Absence of a
mention is unknown, not proof that an amenity is absent. Explicit negation must
also be preserved, for example “no swimming pool.” Advertised features remain
source claims, not independent physical verification.

## Extraction and review

Start with a small agreed feature vocabulary and test it against saved examples
from all portals. Use title and primary-description identity statements first;
parse feature lists in their own context. Avoid indiscriminate keyword matching
across contact text, agent inventories, landmarks, alternative uses, or unrelated
properties. Description clues can refine a supported asset, but do not erase
genuine contradictions between the title and description.

The first useful candidates are home office, private/shared cinema, BQ, pool,
gym, furnishing, and explicitly stated ensuite facilities. Their exact keys,
values, and relation categories are proposals, not accepted additions. New
attributes need regression examples for negation, shared facilities, absent
counts, multiple offers, and conflicting claims.

## Implementation sequence

1. Implement the accepted classification-context corrections without introducing
   feature columns. Keep the evidence showing why an amenity was not another
   property type.
2. Review feature definitions and examples together. Choose an additive storage
   model and consumer contract, including unknowns, conflicting claims, and
   source timestamps. Revisit count normalization as its own change.
3. Build a versioned offline extraction preview. Show proposed attributes and
   evidence, the unsupported phrases, and representative errors. Evaluate on a
   reviewed set; do not present extraction volume as accuracy.
4. Add incremental migrations and persistence in a separate PR against master.
   Apply reviewed historical extraction with audit and resume protections while
   preserving original descriptions, prices, and lifecycle observations.

Research consumers should be able to query type, bedrooms, scope, and features
independently, while tracing each value back to the actual wording.
