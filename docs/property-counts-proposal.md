# Property counts: proposal for review

Status: count semantics and storage approach accepted by the user on
17 November 2026. Retained design record; the implementation and consolidated
contract/operations guide are in [PR #15](https://github.com/islajr/property-scraper/pull/15).
Concrete extraction outputs remain subject to review before production use.
This extends the [feature proposal](property-features-proposal.md). It introduces
no columns, classifier changes, production writes, or portal requests.

The existing classification contract records asset scope but no dedicated numeric
unit count. Broadness and quantity are separate questions: HOUSE may lack form
detail, while even DETACHED_DUPLEX does not establish how many are offered.
Refine a broad form when the evidence supports it; record quantity separately.

## Count observations rather than an unqualified number

An integer needs a counted entity and a relationship to the offer. “One block
containing four flats” supplies two counts, both correct and useful. Neither
should overwrite the other or become a bedroom count.

Proposed observations should identify:

- **Value:** a stated positive integer, range, or lower bound. Keep “at least
  four” and “four to six” distinct from an exact four.
- **Counted entity:** room, dwelling unit, building, or another agreed asset
  entity. Preserve the advertised form alongside that entity where established.
- **Relationship:** assets offered together, units contained in those assets,
  bedrooms per dwelling, or development availability. These are different facts.
- **Parent/offer reference:** which building, bundle, or offer option the count
  describes. Do not mix per-unit and all-units alternatives in one number.
- **Evidence:** source field, exact wording, observation time, extraction rule,
  and whether the value is stated, derived, conflicting, or unknown.

These are semantic requirements, not final field names or a decision between
columns, JSON, or normalized child tables. Choose storage after reviewing the
examples and how research consumers will query the values.

## Accepted semantic examples

| Advert wording | Counts supported by the wording | What remains unestablished |
| --- | --- | --- |
| Three detached duplexes sold together | 3 duplex assets offered as a bundle | Bedrooms in each; do not invent them |
| One room in a shared apartment | 1 room offered | Total rooms in the apartment and private facilities |
| Entire block containing four flats | 1 building offered; 4 dwelling units contained | Bedroom counts and whether flats are separately available |
| Four three-bedroom flats, all sold together | 4 dwelling assets offered; 3 bedrooms per dwelling | Whether they comprise an entire building |
| Two buildings containing fourteen residential units in total | 2 buildings offered, if the advert explicitly offers both; 14 contained dwelling units across them | Distribution across buildings; do not assume seven in each |
| Four flats available individually or together | An explicit 1-flat option and a 4-flat bundle option, linked to their respective pricing evidence | Which option a consumer intends to compare; do not duplicate the advert into independent property records |
| A three-bedroom house | 3 bedrooms in the identified house | A numeric asset count unless individually offered scope is explicitly established |
| House for sale / room available | A form clue, subject to the other evidence | A stored numeric count; do not silently default to one |
| All rooms ensuite | A facilities claim | Number of rooms or bedrooms |
| Six apartments available in the development | 6 available units in development inventory | Whether the advertised price covers one unit or a fixed six-unit bundle |

Singular “one” is evidence when it explicitly identifies the offered asset.
Likewise, a reviewed rule may establish a single individually offered asset from
clear offer wording. A type code, grammatical singular, or an existing UNIT
default is not sufficient by itself to manufacture an exact count.

## Missing values and derived values

A missing count stays unknown, with the missing question and next action in the
resolution worklist. Distinguish unknown from not applicable and from an explicit
zero: no bedrooms in an explicitly advertised studio is not the same observation
as an unspecified bedroom count. Any zero-count semantics require review for
the particular attribute; an offered asset count must not be zero.

If four flats each explicitly have three bedrooms, twelve total bedrooms is a
possible derived value. Keep the calculation and its inputs separate from the
source-stated per-dwelling count. Do not multiply counts unless the units,
relationship, and uniformity are established. Mixed layouts require a breakdown
instead of a single bedrooms-per-unit value.

Conflicting title and description counts retain both claims and their evidence.
A later portal observation does not silently replace the meaning or dates of
the earlier observation. Descriptions, prices, and lifecycle history remain intact.

## Work to prepare before implementation

1. The user has accepted the semantic distinctions and examples above. Preserve
   those decisions while investigating malformed and contradictory numbers,
   mixed bedroom layouts, per-unit prices, bundles, and availability statements.
2. The read-only profile in [PR #14](https://github.com/islajr/property-scraper/pull/14)
   scanned 28,955 listings and found building/unit count clues in 1,744 after a
   numeric-boundary correction (superseding the preliminary 1,794). It reports
   literal candidates, possible conflicts, alternative-offer hints, and pattern
   gaps; these are not verified counts or confirmed absences. The old bedroom
   values, including 1234, were not used as a unit-count source.
3. The accepted storage approach is implemented in PR #15, including an additive
   schema, append-only decisions, freshness checks, and query examples. Review
   compatibility with prices, property identity, and downstream aggregation there.
4. PR #15 includes extraction, validation, regression cases, and a read-only
   preview. Review the outputs before a bounded production caller is implemented.
   Discovery integration and production count writes remain follow-up work.

## Relationship to the open PRs

[PR #12](https://github.com/islajr/property-scraper/pull/12) remains the joint review
and documentation draft. This proposal belongs there for study and discussion.
[PR #13](https://github.com/islajr/property-scraper/pull/13) contains only the agreed
classification spelling/context corrections, v2 registration, tests, and preview.
It introduces no count or structured-feature storage. It can be reviewed on that
scope independently; a merge does not complete or implement this proposal.

No PR is merged by this documentation change. The read-only count profile is
complete in PR #14, and PR #15 contains the storage/extraction implementation.
Land PR #14 first, then rebase PR #15 against master. Classification PR #13 is
independent. The next count milestone is reviewing the extraction preview and
preparing a bounded caller, not running an unrestricted production backfill.
