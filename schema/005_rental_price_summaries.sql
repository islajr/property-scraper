-- Current observations only. These views do not reconstruct historical prices.
BEGIN;
CREATE OR REPLACE VIEW raw_data.rental_price_summary AS
SELECT city, neighbourhood, price_type, price_period, price_period_count,
       COUNT(*) AS listing_count,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price_kobo) AS median_price_kobo,
       MIN(pricing_observed_at) AS oldest_quote_observed_at,
       MAX(pricing_observed_at) AS newest_quote_observed_at
FROM raw_data.comparable_rental_prices
WHERE listing_status = 'ACTIVE'
GROUP BY city, neighbourhood, price_type, price_period, price_period_count;

CREATE OR REPLACE VIEW raw_data.rental_pricing_coverage AS
SELECT source, price_type, listing_status, price_period_status,
       COUNT(*) AS listing_count,
       COUNT(*) FILTER (WHERE price_period_status='KNOWN' AND price_currency='NGN'
                        AND price_basis='PROPERTY' AND price_kobo>0 AND NOT price_parse_failed) AS comparable_count
FROM raw_data.scraped_listings
WHERE price_type IN ('FOR_RENT','FOR_SHORT_LET')
GROUP BY source, price_type, listing_status, price_period_status;
COMMIT;
