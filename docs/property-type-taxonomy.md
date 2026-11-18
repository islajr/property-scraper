# Property vocabulary

`property-types-v3` retains the 19 legacy codes and the 17 previously agreed
additions, and adds HOSTEL, GAS_PLANT and EVENT_VENUE (39 codes). These specialist
types preserve distinctions that a generic commercial fallback would lose.

Type describes the offered asset's form or function. Bedrooms, counts, amenities,
attachment, scope, advertised land use, transaction purpose and pricing are
separate fields. HOUSE and ROOM remain valid when no narrower identity is stated;
no singular noun supplies a numeric quantity of one.

| Code | Category | Family | Default attachment | Default scope |
| --- | --- | --- | --- | --- |
| BLOCK_OF_FLATS | RESIDENTIAL | BLOCK_OF_FLATS | NULL | WHOLE_BUILDING |
| BUNGALOW | RESIDENTIAL | BUNGALOW | NULL | NULL |
| COMMERCIAL_OTHER | COMMERCIAL | COMMERCIAL_OTHER | NULL | NULL |
| COMMERCIAL_SHOP | COMMERCIAL | COMMERCIAL_SHOP | NULL | NULL |
| DETACHED_BUNGALOW | RESIDENTIAL | BUNGALOW | DETACHED | NULL |
| DETACHED_DUPLEX | RESIDENTIAL | DUPLEX | DETACHED | NULL |
| DUPLEX | RESIDENTIAL | DUPLEX | NULL | NULL |
| EVENT_VENUE | COMMERCIAL | EVENT_VENUE | NULL | NULL |
| FACTORY | COMMERCIAL | FACTORY | NULL | NULL |
| FILLING_STATION | COMMERCIAL | FILLING_STATION | NULL | NULL |
| FLAT_APARTMENT | RESIDENTIAL | APARTMENT | NULL | UNIT |
| GAS_PLANT | COMMERCIAL | GAS_PLANT | NULL | NULL |
| GUEST_HOUSE | COMMERCIAL | GUEST_HOUSE | NULL | WHOLE_BUILDING |
| HOSPITAL | COMMERCIAL | HOSPITAL | NULL | NULL |
| HOSTEL | COMMERCIAL | HOSTEL | NULL | NULL |
| HOTEL | COMMERCIAL | HOTEL | NULL | WHOLE_BUILDING |
| HOUSE | RESIDENTIAL | HOUSE | NULL | NULL |
| LAND | LAND | LAND | NULL | LAND_PARCEL |
| LAND_SERVICED | LAND | LAND | NULL | LAND_PARCEL |
| MAISONETTE | RESIDENTIAL | APARTMENT | NULL | UNIT |
| MANSION | RESIDENTIAL | HOUSE | NULL | NULL |
| MINI_FLAT | RESIDENTIAL | APARTMENT | NULL | UNIT |
| MIXED_USE_PROPERTY | MIXED_USE | MIXED_USE | NULL | NULL |
| OFFICE | COMMERCIAL | OFFICE | NULL | NULL |
| OFFICE_BUILDING | COMMERCIAL | OFFICE_BUILDING | NULL | WHOLE_BUILDING |
| PENTHOUSE | RESIDENTIAL | APARTMENT | NULL | UNIT |
| RESTAURANT | COMMERCIAL | RESTAURANT | NULL | NULL |
| ROOM | RESIDENTIAL | ROOM | NULL | UNIT |
| SCHOOL | COMMERCIAL | SCHOOL | NULL | NULL |
| SELF_CONTAINED | RESIDENTIAL | ROOM | NULL | UNIT |
| SEMI_DETACHED_BUNGALOW | RESIDENTIAL | BUNGALOW | SEMI_DETACHED | NULL |
| SEMI_DETACHED_DUPLEX | RESIDENTIAL | DUPLEX | SEMI_DETACHED | NULL |
| SHOWROOM | COMMERCIAL | SHOWROOM | NULL | NULL |
| STUDIO | RESIDENTIAL | APARTMENT | NULL | UNIT |
| TERRACED_BUNGALOW | RESIDENTIAL | BUNGALOW | TERRACED | NULL |
| TERRACED_DUPLEX | RESIDENTIAL | DUPLEX | TERRACED | NULL |
| TOWNHOUSE | RESIDENTIAL | HOUSE | NULL | NULL |
| VILLA | RESIDENTIAL | HOUSE | NULL | NULL |
| WAREHOUSE | COMMERCIAL | WAREHOUSE | NULL | NULL |

Defaults describe classification facets, not verified legal ownership or numeric
counts. Explicit evidence can distinguish individual units, multiple units,
whole buildings and land parcels. Commercial category does not establish that
an entire business, building or site is owned or for sale.

CLASSIFIED requires a supported code and evidence. AMBIGUOUS retains conflicting
primary asset claims; INSUFFICIENT_EVIDENCE means identity could not be established;
UNSUPPORTED marks an unmapped asset label. Their canonical type is NULL.
LEGACY_UNREVIEWED exists only for observations not yet processed under this contract.

Spelling/context aliases have word boundaries. Marketing adjectives, transaction
prefixes and locations do not become type codes. Specific compatible forms refine
broad labels; conflicting assets do not resolve through arbitrary precedence.
Source-bound user review decisions can settle individual saved snapshots and
expire when their source evidence changes.

See [classification evidence rules](property-types.md), [count semantics](property-counts.md)
and [the current consumer/operations contract](property-unification.md).
