import os
import sys
import psycopg2
from psycopg2.extras import DictCursor
import hashlib
from datetime import datetime, timedelta, date

project_root = "/home/isla-jr/Documents/se-workspace/property-scraper"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))

def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not found in environment.")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    return conn

def calculate_percentile(sorted_data, pct):
    if not sorted_data:
        return None
    n = len(sorted_data)
    idx = (pct / 100.0) * (n - 1)
    low = int(idx)
    high = min(n - 1, low + 1)
    weight = idx - low
    return float(sorted_data[low] * (1.0 - weight) + sorted_data[high] * weight)

def main():
    print("Rebuilding neighbourhood snapshots table...")
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 1. Fetch listings that are normalised
            print("Fetching normalised listings...")
            cur.execute("""
                SELECT id, city, neighbourhood, first_seen_at, last_seen_at, listing_status, price_kobo 
                FROM raw_data.scraped_listings
                WHERE neighbourhood_normalised = True
                    AND city IS NOT NULL
                    AND neighbourhood IS NOT NULL
            """)
            listings = cur.fetchall()
            print(f"Loaded {len(listings)} normalised listings.")

            if not listings:
                print("No normalised listings found to process.")
                return

            # 2. Fetch listing history for price changes
            print("Fetching price change history...")
            cur.execute("""
                SELECT listing_id, event_date, old_value, new_value
                FROM raw_data.listing_history
                WHERE event_type = 'PRICE_CHANGE'
                ORDER BY event_date DESC, id DESC
            """)
            history_rows = cur.fetchall()
            print(f"Loaded {len(history_rows)} price change history events.")

            # Group history by listing_id
            history_by_listing = {}
            for row in history_rows:
                lid = row["listing_id"]
                if lid not in history_by_listing:
                    history_by_listing[lid] = []
                history_by_listing[lid].append({
                    "event_date": row["event_date"],
                    "old_value": row["old_value"],
                    "new_value": row["new_value"]
                })

            # 3. Determine start date (oldest first_seen_at)
            min_first_seen = min(row["first_seen_at"] for row in listings)
            print(f"Oldest first_seen_at: {min_first_seen}")

            # Find Monday of that week
            start_date = min_first_seen.date()
            start_monday = start_date - timedelta(days=start_date.weekday())
            print(f"Starting timeline from Monday: {start_monday}")

            # Define weeks up to the most recent completed week (ending last Sunday)
            today = date.today()
            current_monday = today - timedelta(days=today.weekday())
            last_completed_sunday = current_monday - timedelta(days=1)
            print(f"Ending timeline at Sunday: {last_completed_sunday}")

            weeks = []
            w_start = start_monday
            while w_start + timedelta(days=6) <= last_completed_sunday:
                w_end = w_start + timedelta(days=6)
                weeks.append((w_start, w_end))
                w_start += timedelta(days=7)

            print(f"Generated {len(weeks)} completed weeks.")

            # 4. Truncate target table
            print("Truncating market.neighbourhood_snapshots...")
            cur.execute("TRUNCATE TABLE market.neighbourhood_snapshots")
            print("Truncated successfully.")

            # 5. Group listings by (city, neighbourhood) for aggregation loop
            by_neighbourhood = {}
            for row in listings:
                key = (row["city"], row["neighbourhood"])
                if key not in by_neighbourhood:
                    by_neighbourhood[key] = []
                by_neighbourhood[key].append(row)

            # 6. Aggregate data week-by-week
            snapshots_to_insert = []
            computed_at = datetime.now()

            for w_start, w_end in weeks:
                w_start_dt = datetime.combine(w_start, datetime.min.time()).replace(tzinfo=min_first_seen.tzinfo)
                w_end_dt = datetime.combine(w_end, datetime.max.time()).replace(tzinfo=min_first_seen.tzinfo)
                snapshot_week_str = w_start.strftime("%Y-%m-%d")

                for (city, neighbourhood), items in by_neighbourhood.items():
                    # Find active listings in this week
                    active_in_week = []
                    for item in items:
                        first_seen = item["first_seen_at"]
                        last_seen = item["last_seen_at"]
                        status = item["listing_status"]

                        # Listed on or before week end, and active or not removed before week start
                        is_active_this_week = (
                            first_seen <= w_end_dt and 
                            (status == 'ACTIVE' or last_seen >= w_start_dt)
                        )
                        if is_active_this_week:
                            active_in_week.append(item)

                    active_count = len(active_in_week)

                    # Filter: ignore neighbourhoods with only one listing in that week
                    if active_count <= 1:
                        continue

                    # Calculate new listings count
                    new_count = 0
                    for item in active_in_week:
                        if w_start_dt <= item["first_seen_at"] <= w_end_dt:
                            new_count += 1

                    # Reconstruct historical prices for active listings as of w_end
                    prices = []
                    days_on_market_list = []
                    price_reduced_count = 0

                    for item in active_in_week:
                        lid = item["id"]
                        first_seen = item["first_seen_at"]
                        last_seen = item["last_seen_at"]
                        status = item["listing_status"]

                        # Historical price reconstruction
                        price = item["price_kobo"]
                        history = history_by_listing.get(lid, [])
                        for ev in history:
                            if ev["event_date"] > w_end:
                                if ev["old_value"] is not None:
                                    price = ev["old_value"]
                        
                        if price is not None:
                            prices.append(price)

                        # Check for price reduction in this week
                        has_reduction = False
                        for ev in history:
                            if w_start <= ev["event_date"] <= w_end:
                                if ev["old_value"] is not None and ev["new_value"] is not None:
                                    if ev["new_value"] < ev["old_value"]:
                                        has_reduction = True
                                        break
                        if has_reduction:
                            price_reduced_count += 1

                        # Days on market
                        if status == 'REMOVED' and last_seen <= w_end_dt:
                            presence_end = last_seen.date()
                        else:
                            presence_end = w_end
                        
                        days = (presence_end - first_seen.date()).days
                        days_on_market_list.append(max(0, days))

                    avg_dom = round(sum(days_on_market_list) / len(days_on_market_list), 1) if days_on_market_list else None

                    # Percentiles
                    if prices:
                        prices_sorted = sorted(prices)
                        median = calculate_percentile(prices_sorted, 50)
                        p25 = calculate_percentile(prices_sorted, 25)
                        p75 = calculate_percentile(prices_sorted, 75)
                        p90 = calculate_percentile(prices_sorted, 90)
                    else:
                        median = p25 = p75 = p90 = None

                    # Generate ID matching the format: md5(neighbourhood + snapshot_week)
                    id_str = f"{neighbourhood}{snapshot_week_str}"
                    snap_id = hashlib.md5(id_str.encode()).hexdigest()

                    snapshots_to_insert.append((
                        snap_id,
                        city,
                        neighbourhood,
                        w_start,
                        avg_dom,
                        computed_at,
                        active_count,
                        new_count,
                        price_reduced_count,
                        median,
                        p25,
                        p75,
                        p90
                    ))

            # 7. Write to database in batches
            print(f"Calculated {len(snapshots_to_insert)} snapshot rows to insert.")
            inserted_count = 0
            batch_size = 200

            for i in range(0, len(snapshots_to_insert), batch_size):
                batch = snapshots_to_insert[i:i+batch_size]
                cur.executemany("""
                    INSERT INTO market.neighbourhood_snapshots (
                        id, city, neighbourhood, snapshot_week, avg_days_on_market, computed_at, 
                        active_listing_count, new_listings_count, price_reduced_count, 
                        median_price_kobo, p25, p75, p90
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, batch)
                inserted_count += len(batch)
                print(f"  inserted {inserted_count}/{len(snapshots_to_insert)} ...")

            print(f"Successfully rebuilt all completed weekly neighbourhood snapshots! Total inserted: {inserted_count} rows.")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
