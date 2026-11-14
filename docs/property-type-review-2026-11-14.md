# Property classification review: round one

Status: draft for joint review. Every proposed decision below is **PENDING**.
This document changes no classifier rules, taxonomy codes, or production data.
The accepted [taxonomy contract](property-type-taxonomy.md) remains in force.

The aim is to settle the meaning of a property before changing more records.
Bedrooms, unit counts, marketing language, transaction purpose, and amenities
remain separate from its type. The open questions are how to read incomplete
listing language and how to represent the asset actually being offered.

## Evidence and coverage

Read-only production snapshot: **14 November 2026, 04:31:28 UTC** (05:31:28 WAT).
All 28,102 rows were counted. The local review export contains all 3,298 rows
whose status is not CLASSIFIED, plus 111 comparison rows: the first four
CLASSIFIED IDs per portal/type, where available, across eleven selected types.
Descriptions in the private export stop at 6,000 characters. No listing portals
were visited, so these are saved observations, not fresh verification.

| Current status | Listings |
| --- | ---: |
| CLASSIFIED | 24,804 |
| INSUFFICIENT_EVIDENCE | 2,530 |
| AMBIGUOUS | 506 |
| UNSUPPORTED | 34 |
| LEGACY_UNREVIEWED | 228 |

The 3,070 NULL types comprise INSUFFICIENT_EVIDENCE, AMBIGUOUS, and UNSUPPORTED. The 228
legacy rows retain 207 FLAT_APARTMENT values, five HOUSE values, and 16 malformed
values. These legacy values are not verified canonical classifications.

The 31 cases below are deliberately selected examples spanning all three portals,
not a random sample or an accuracy estimate. A rule must be assessed against the
full preview before rollout. CLASSIFIED comparison rows are included because a
recognized type can still have an incorrect scope or lack supported detail.

Some repeated patterns worth reviewing:

| Saved evidence pattern | Listings | What the count establishes |
| --- | ---: | --- |
| ROOM and FLAT_APARTMENT candidate pair | 79 | A conflict to inspect; some are shared rooms, others are bedroom/amenity parsing errors |
| DUPLEX and MAISONETTE candidate pair | 17 | An overlapping-definition question |
| DUPLEX and OFFICE candidate pair | 14 | Some home-office amenities are being treated as separate assets |
| MINI_FLAT and STUDIO candidate pair | 4 | May be conflicting layout claims or different units in one advert |
| HOTEL and GUEST_HOUSE candidate pair | 9 | Portal wording and actual premises need comparison |
| ROOMSELF in unresolved titles, including Aroomself | 73 | A bounded alias candidate, not 73 approved corrections |
| MASSIONETTE in unresolved titles | 10 | A spelling candidate |
| MINIFAT in unresolved titles | 1 | A spelling candidate |
| Numeric BED ROOM wording in unresolved titles | 20 | A likely tokenization issue to inspect |

Candidate-pair counts come from saved classifier evidence. Spelling/spacing
counts are case-insensitive title scans of non-CLASSIFIED rows. Patterns can
overlap; do not sum them or treat them as recoverable totals.

## Decisions to settle

| Decision | Proposed starting rule | Boundary to retain |
| --- | --- | --- |
| D1: Apartment layouts | Keep FLAT_APARTMENT broad; refine to MINI_FLAT, STUDIO, or SELF_CONTAINED when explicit supporting wording establishes it | One bedroom alone establishes none of these subtypes; private facilities do not prove a studio layout |
| D2: Incidental features | Bedroom wording, ensuite rooms, home offices, BQ, and private cinemas do not create separate offered assets | An actual separately offered office or cinema must still be recognized |
| D3: Description evidence | Allow a bounded description statement to refine a compatible title or settle what is offered | Preserve true title/description conflicts; never give the description unconditional precedence |
| D4: Units and buildings | Use UNIT, MULTIPLE_UNITS, and WHOLE_BUILDING according to explicit offer evidence | A number of units does not prove a whole building; unit-or-bundle offers need an explicit representation |
| D5: Primary-type overlaps | Review maisonette/duplex, studio/mini-flat, hotel/guest-house, and shop/office separately | No blanket winner or new MIXED_USE classification based only on two keywords |
| D6: New vocabulary | Assess hostels, gas plants, event venues, religious premises, and farms with definitions and examples | First exclude amenities, landmarks, alternative uses, and investment-package ambiguity |

A current UNIT scope means an individually offered asset, not proof of private
facilities. New fields for unit count, layout, features, or offer options would
need a separate schema and compatibility proposal. None is introduced here.
A proposed result below is a human review interpretation, not a claim that the
current classifier or schema already implements it.

## Cases

Read the evidence first, then the proposed result. Use ACCEPT, CHANGE, or HOLD in
the [CSV worksheet](property-type-review-2026-11-14.csv), with a short reason in
reviewer_notes. ACCEPT agrees with the case interpretation; it does not approve
an automatic production change or settle every example in the group.

## A. Apartment and room definitions

Start here. These five examples establish the difference between an apartment, a mini flat, a studio, a broad self-contained unit, and a room in a shared flat.

| Case / source listing | Current decision | Saved evidence | Proposed result and reason |
| --- | --- | --- | --- |
| R01 · [1](https://propertypro.ng/property/3-bedroom-flat-apartment-for-sale-located-at-dakibiyu-side-of-wuye-wuye-abuja-5PFSK) · propertypro | FLAT_APARTMENT; CLASSIFIED; scope UNIT | TITLE: “3 Bedroom Flat” | **FLAT_APARTMENT / UNIT**. Keep bedrooms separate. This is the ordinary apartment baseline. |
| R02 · [152](https://privateproperty.ng/listings/1-bedroom-mini-flat-for-rent-along-adeoyo-roundabout-main-ringroad-ibadan-ring-road-ibadan-oyo-0PDJQG) · privateproperty | MINI_FLAT; CLASSIFIED; scope UNIT | TITLE: “A Room And Parlor Self Contained” | **MINI_FLAT / UNIT**. An explicit room-and-parlour layout refines the broader self-contained wording. |
| R03 · [165](https://privateproperty.ng/listings/1-bedroom-studio-apartment-for-rent-ivy-homes-lekky-ikota-ikota-lekki-lagos-0PDJQE) · privateproperty | STUDIO; CLASSIFIED; scope UNIT | TITLE: “Studio Apartment Available With Open Plan Kitchen” | **STUDIO / UNIT**. Keep an explicitly advertised studio distinct; do not derive it from one bedroom. |
| R04 · [83](https://propertypro.ng/property/1-bedroom-flat-apartment-for-rent-lekki-lagos-5JPNF) · propertypro | SELF_CONTAINED; CLASSIFIED; scope UNIT | TITLE: “Self Contained” | **SELF_CONTAINED / UNIT**. Keep the advertised broad label. Private kitchen wording alone does not prove a studio layout. |
| R05 · [862](https://privateproperty.ng/listings/1-bedroom-shared-apartment-for-rent-rockstone-estate-badore-ajah-lagos-2PDJVS) · privateproperty | NULL; AMBIGUOUS; scope unknown | DESCRIPTION: “room apartment in a shared flat” | **ROOM / UNIT**. The offered asset is a room in a shared flat, rather than the entire apartment. |

## B. Spelling, context, and compatible refinement

These proposals use existing type codes. They require bounded rules and counterexamples, rather than global text substitutions or scanning every amenity.

| Case / source listing | Current decision | Saved evidence | Proposed result and reason |
| --- | --- | --- | --- |
| R06 · [57](https://propertypro.ng/property/4-bedroom-house-for-sale-shonibare-estate-maryland-lagos-6PDKL) · propertypro | NULL; INSUFFICIENT_EVIDENCE; scope unknown | TITLE: “4bed Massionette+bq” | **MAISONETTE / UNIT**. Consider the bounded spelling alias massionette. BQ does not change the primary type. |
| R07 · [69](https://propertypro.ng/property/1-bedroom-flat-apartment-for-rent-ikosi-ketu-lagos-ikosi-ketu-kosofe-ikosi-lagos-2PKCB) · propertypro | NULL; INSUFFICIENT_EVIDENCE; scope unknown | DESCRIPTION: “A Client is expected to rent the 5 units of Minifat at Once” | **MINI_FLAT / MULTIPLE_UNITS**. Both Mini Flat and Minifat occur in the description. Five units must be rented together; do not claim a whole building. |
| R08 · [3346](https://propertypro.ng/property/1-bedroom-flat-apartment-for-rent-akoka-yaba-lagos-yaba-lagos-9PMYD) · propertypro | NULL; INSUFFICIENT_EVIDENCE; scope unknown | TITLE: “Roomself Contain” | **SELF_CONTAINED / UNIT**. Consider the bounded roomself contain alias; this is not evidence of a studio. |
| R09 · [1666](https://privateproperty.ng/listings/3-bedroom-block-of-flats-for-rent-back-of-bolad-along-akala-express-oluyole-extension-akala-express-ibadan-oyo-9PDKCY) · privateproperty | NULL; AMBIGUOUS; scope unknown | TITLE: “3bed Room Flat” | **FLAT_APARTMENT / UNIT**. Treat bed room as bedroom wording, not a second offered ROOM asset. |
| R10 · [4472](https://propertypro.ng/property/2-bedroom-flat-apartment-for-rent-borno-way-yaba-lagos-yaba-lagos-0PMYZ) · propertypro | NULL; AMBIGUOUS; scope unknown | TITLE: “All Rooms Ensuite Flat” | **FLAT_APARTMENT / UNIT**. All rooms ensuite describes facilities within the flat, not separately offered rooms. |
| R11 · [855](https://privateproperty.ng/listings/4-bedroom-semi-detached-duplex-for-rent-parkview-estate-ikoyi-lagos-4PDJVW) · privateproperty | NULL; AMBIGUOUS; scope unknown | DESCRIPTION: “added functionality with a dedicated office space and 2 boys’ quarters” | **SEMI_DETACHED_DUPLEX / scope not established**. The description identifies a home office within the primary duplex. Do not classify the office or BQ as separate assets. |
| R12 · [16313](https://propertypro.ng/property/5-bedroom-flat-apartment-for-shortlet-lekki-phase-1-lekki-lagos-1PXAE) · propertypro | NULL; UNSUPPORTED; scope unknown | DESCRIPTION: “Luxury 5 Bedroom Duplex” | **DUPLEX / scope not established**. The description identifies a duplex; private cinema is an amenity. A cinema keyword must not block identity recovery. |
| R13 · [527](https://nigeriapropertycentre.com/for-rent/commercial/plaza-complex-mall/lagos/lekki/lekki-phase-1/3422175-30-square-metres-shop-space-available-in-admiralty-mall) · nigeriapropertycentre | NULL; INSUFFICIENT_EVIDENCE; scope unknown | DESCRIPTION: “30sqm shop space available for rent” | **COMMERCIAL_SHOP / UNIT**. The generic mall title describes the setting. The description identifies the offered shop. |
| R14 · [13](https://propertypro.ng/property/4-bedroom-house-for-sale-ikate-lekki-lagos-1PKBW) · propertypro | DUPLEX; CLASSIFIED; scope unknown | DESCRIPTION: “4 BEDROOM TERRACE DUPLEX WITH BQ” | **TERRACED_DUPLEX / scope not established**. Already CLASSIFIED as DUPLEX. Consider compatible description-based refinement rather than accepting a broad title as complete. |

## C. Units, blocks, and legacy cleanup

Preserve the historic value in append-only audit. An unresolved replacement has a NULL canonical type and an appropriate unresolved status, not a new title-shaped type. Missing scope evidence and conflicting asset evidence must be distinguished.

| Case / source listing | Current decision | Saved evidence | Proposed result and reason |
| --- | --- | --- | --- |
| R15 · [8](https://propertypro.ng/property/house-for-sale-anfani-off-ring-road-challenge-aso-ibadan-anfani-ibadan-oyo-9PKBW) · propertypro | FLAT_APARTMENT; CLASSIFIED; scope UNIT | TITLE: “5 Flat Of 2no Of 2 Bedrm & 3no Of 1 Bedrm” | **FLAT_APARTMENT / MULTIPLE_UNITS**. Already CLASSIFIED with UNIT scope. The title offers five flats with mixed bedroom counts; do not claim one unit or a single bedroom count. |
| R16 · [3794](https://privateproperty.ng/listings/3-bedroom-block-of-flats-for-rent-peace-estate-sangotedo-ajah-lagos-1PDKSR) · privateproperty | FOR_RENT:_THERE_BEDROOM; LEGACY_UNREVIEWED; scope unknown | DESCRIPTION: “3 bedroom Block Of Flats For Rent” | **No canonical type yet / scope unresolved**. The description supports reading the title typo There as three, but does not establish whether a unit or whole block is offered. |
| R17 · [8715](https://privateproperty.ng/listings/2-bedroom-block-of-flats-for-rent-opposite-barakuda-beach-okun-ajah-lagos-4PDLRQ) · privateproperty | FOR_RENT:_MASSIVE_TWO_BEDROOM_UPSTAIRS; LEGACY_UNREVIEWED; scope unknown | TITLE: “Massive Two Bedroom Upstairs” | **No canonical type yet / scope unresolved**. Massive and upstairs are not types. The description says block of flats without resolving the offered scope. The same title occurs on IDs 8721 and 8722. |
| R18 · [6632](https://propertypro.ng/property/10-bedroom-house-for-sale-aare-oluyole-oluyole-estate-ibadan-oyo-4PPNG) · propertypro | 4_UNITS_OF_3_BEDROOM_AT_AARE_OLUYOLE; LEGACY_UNREVIEWED; scope unknown | DESCRIPTION: “For Sale: A block of 4 flats on a parcel of land” | **BLOCK_OF_FLATS / WHOLE_BUILDING**. The description explicitly offers a block. Preserve the old title-shaped value in audit, not in the canonical type. Do not derive total bedrooms. |
| R19 · [22969](https://nigeriapropertycentre.com/for-sale/houses/block-of-flats/lagos/shomolu/bariga/3685562-block-of-4-flats-3-bedroom-each) · nigeriapropertycentre | BLOCK_OF; LEGACY_UNREVIEWED; scope unknown | TITLE: “Block of 4 Flats, 3 Bedroom Each” | **BLOCK_OF_FLATS / WHOLE_BUILDING**. A block is offered, with four flats and an explicit bedroom count per flat. Those are separate facts. |
| R20 · [358](https://nigeriapropertycentre.com/for-sale/houses/block-of-flats/abuja/karmo/2722598-3-bedroom-apartment) · nigeriapropertycentre | FLAT_APARTMENT; LEGACY_UNREVIEWED; scope unknown | DESCRIPTION: “2 bedroom apartment.” | **FLAT_APARTMENT / UNIT**. The description identifies a unit despite the generic block-of-flats title. This requires a bounded title/description scope rule. |
| R21 · [15921](https://nigeriapropertycentre.com/for-sale/houses/block-of-flats/abuja/kuje/3464033-a-4-units-of-a-2-bedroom-block-of-flat-with-an-open-kitchen) · nigeriapropertycentre | BLOCK_OF; LEGACY_UNREVIEWED; scope unknown | DESCRIPTION: “(PER UNIT)” | **No single canonical decision yet / unit-or-bundle offer**. The description also quotes ALL UNITS. Keep both offer options visible; do not pick a scope from the headline alone. |
| R22 · [408](https://nigeriapropertycentre.com/for-sale/houses/block-of-flats/lagos/ikeja/gra/3383969-luxury-3-bedrooms-apartment) · nigeriapropertycentre | FLAT_APARTMENT; LEGACY_UNREVIEWED; scope unknown | TITLE: “3 bedroom block of flats for sale” | **No canonical type yet / scope unresolved**. There is no saved description. Bedroom count alone cannot settle the asset scope. |
| R23 · [305](https://nigeriapropertycentre.com/for-sale/houses/block-of-flats/lagos/shomolu/3422308-land-on-a-commercial-road-at-shomolu-land-size-600-sqm-asking-price) · nigeriapropertycentre | FLAT_APARTMENT; LEGACY_UNREVIEWED; scope unknown | DESCRIPTION: “Now SellingLand on a commercial road” | **AMBIGUOUS / no canonical type**. The block-of-flats title conflicts with a land description. Do not solve this by always trusting descriptions. |

## D. Overlapping labels and multi-offer listings

These need a definition or representation decision. Avoid hiding genuine uncertainty with a keyword priority rule.

| Case / source listing | Current decision | Saved evidence | Proposed result and reason |
| --- | --- | --- | --- |
| R24 · [3511](https://privateproperty.ng/listings/3-bedroom-maisonette-for-sale-lekki-phase-1-lagos-2PDKUD) · privateproperty | NULL; AMBIGUOUS; scope unknown | TITLE: “3 Bedroom Maisonette Duplex With A Bq” | **Decision needed: MAISONETTE precedence or AMBIGUOUS**. Both terms identify the primary asset. Review whether duplex describes its internal levels; do not install blanket precedence without an agreed definition. |
| R25 · [10064](https://privateproperty.ng/listings/1-bedroom-mini-flat-for-rent-van-daniel-estate-orchid-road-lekki-lagos-9PDLXS) · privateproperty | NULL; AMBIGUOUS; scope unknown | TITLE: “Studio Room And Parlor” | **Keep AMBIGUOUS pending layout evidence**. Studio and room-and-parlour conflict under the proposed distinction. The description calls it a mini flat, without a verified layout. |
| R26 · [19318](https://privateproperty.ng/listings/1-bedroom-mini-flat-for-rent-victoria-island-lagos-6PDPUK) · privateproperty | NULL; AMBIGUOUS; scope unknown | DESCRIPTION: “units of mini flats and studio apartments” | **Keep AMBIGUOUS at listing level / multiple offer types**. Separate rents are advertised for studios and mini flats. This is a multi-offer listing, not necessarily contradictory wording for one unit. |
| R27 · [4466](https://propertypro.ng/property/commercial-property-for-rent-guzape-guzape-abuja-0PMZA) · propertypro | NULL; AMBIGUOUS; scope unknown | TITLE: “Shop/office Space” | **Decision needed: broad commercial unit or AMBIGUOUS**. Alternative permitted uses do not automatically make a mixed-use building. Agree how to represent a flexible commercial unit. |

## E. Candidate categories

These are vocabulary questions, not approved new codes. Review more examples and counterexamples before selecting names, categories, families, or default scopes.

| Case / source listing | Current decision | Saved evidence | Proposed result and reason |
| --- | --- | --- | --- |
| R28 · [28010](https://privateproperty.ng/listings/hostel-for-sale-morayo-hostel-opposite-olabisi-onabanjo-university-ago-iwoye-ijebu-north-ogun-6PDSYW) · privateproperty | NULL; UNSUPPORTED; scope unknown | TITLE: “Affordable Hostel” | **Candidate HOSTEL; definition and scope pending**. The description advertises hostel investment options. Establish whether the offer is a room, unit, building, or investment package before assigning scope. |
| R29 · [22974](https://nigeriapropertycentre.com/for-sale/commercial/filling-stations/lagos/epe/3685549-gas-plant-property) · nigeriapropertycentre | NULL; UNSUPPORTED; scope unknown | TITLE: “Gas Plant Property” | **Candidate GAS_PLANT; definition pending**. Keep distinct from FILLING_STATION. A nearby school is a landmark, not another offered asset. |
| R30 · [25268](https://nigeriapropertycentre.com/for-rent/event-centre-venue/halls/abuja/life-camp/3716842-event-hall) · nigeriapropertycentre | NULL; UNSUPPORTED; scope unknown | DESCRIPTION: “a brand new event Center/Hall” | **Candidate EVENT_VENUE; definition pending**. Distinguish event premises from a hall amenity inside a home or hotel. |
| R31 · [16382](https://privateproperty.ng/listings/commercial-property-for-sale-cocoa-farm-estate-in-oou-road-ago-iwoye-ogun-area-3PDNTE) · privateproperty | NULL; UNSUPPORTED; scope unknown | TITLE: “Acres Of Cocoa Farm” | **Decision needed: LAND + AGRICULTURAL or a separate farm type**. An operating agricultural asset is not automatically equivalent to a bare parcel. Establish what the sale includes before mapping. |

## From review to implementation

1. Settle group A first, then confirm the context and scope boundaries in B/C.
   Record changes and holds explicitly; do not convert every pending case into
   an accepted label merely because a broad rule sounds reasonable.
2. Add the accepted cases and deliberately contrasting examples to an evaluation
   set. Include held cases where the correct outcome is unresolved. Expand beyond
   these selected examples before making accuracy claims.
3. Implement approved rules in incremental conventional commits and a focused PR
   against master. Any vocabulary or schema additions need explicit definitions
   and compatibility checks. Give changed semantics a new rule version and keep
   existing v1 rollout artifacts and receipts intact.
4. Produce a fresh read-only preview over every row, including CLASSIFIED rows.
   Review type, status, and scope transitions; report what remains unresolved.
   Reuse the audited backfill workflow only after the results are reviewed.
5. Migrate downstream consumers to the shared contract in a separately scoped
   change. Keep unresolved records in coverage counts and filter on CLASSIFIED
   when a query requires an established type.

No production writes or portal requests were made for this review. Bedroom
correction, unit-count storage, new feature fields, consumer migration, and
classification fixes remain separate implementation work.
