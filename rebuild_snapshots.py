"""Retired legacy snapshot entry point.

The old market.neighbourhood_snapshots contract has no listing-type/cadence
columns, and its historical reconstruction mixed incomparable prices. Keep the
command explicit rather than silently overwrite that table with a new meaning.
Current rental comparisons are available through raw_data.rental_price_summary;
coverage (including unresolved records) is in raw_data.rental_pricing_coverage.
External consumers need a versioned historical snapshot contract before rebuilding.
"""


def main():
    raise SystemExit(
        'Legacy snapshot rebuilding is disabled: it mixes sale, rent, and short-let '
        'prices without quote units. Use raw_data.rental_price_summary for current '
        'comparable rental prices; migrate the market snapshot contract before '
        'reconstructing historical series. Existing snapshots are not modified.'
    )


if __name__ == '__main__':
    main()
