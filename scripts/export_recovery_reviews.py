"""Refresh local held-listing reports without contacting PostgreSQL or portals."""
import argparse
import csv
from datetime import datetime, timezone
import html
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile


ACTIONS = {
    'period_unknown': ('Billing period missing', 'Check beside the main price. If no period is stated, leave unknown. If now explicit, note the ID and exact wording for a retry.'),
    'currency_not_ngn': ('Foreign currency', 'Leave unresolved by this tool. Do not convert the amount or assume it is naira.'),
    'purpose_changed': ('Listing category changed', 'Note the ID and correct category for separate investigation. A retry alone cannot correct the saved category.'),
    'page_purpose_conflict': ('Conflicting listing category', 'Check the main page category and report the ID for separate investigation.'),
    'redirected_identity': ('Different property at this link', 'Do not use the destination property price. Report the ID if the original property URL can be established.'),
    'retry_limit_reached': ('Visit limit reached', 'Check the property manually before requesting another attempt. Repeated failures need investigation.'),
}


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent,
                                     prefix=path.name+'.', suffix='.tmp', delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def export_reviews(directory):
    directory = Path(directory).resolve()
    database = directory/'queue.sqlite3'
    conn = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        held = conn.execute("SELECT * FROM jobs WHERE status='held' ORDER BY reason,source,listing_id").fetchall()
    finally:
        conn.close()
    rows = []
    for job in held:
        old, new = json.loads(job['row_json'] or '{}'), json.loads(job['quote_json'] or '{}')
        reason, action = ACTIONS.get(job['reason'], (job['reason'], 'Leave unresolved and investigate this ID before retrying.'))
        rows.append(dict(listing_id=job['listing_id'], portal=job['source'],
                         property_url=old.get('url', ''), saved_category=old.get('price_type', job['price_type']),
                         observed_category=new.get('price_type', ''),
                         displayed_price=new.get('raw_price_text') or old.get('raw_price_text', ''),
                         reason=reason, reason_code=job['reason'], suggested_action=action))
    generated = datetime.now(timezone.utc).isoformat()
    output = io.StringIO(newline='')
    fields = ['listing_id', 'portal', 'property_url', 'saved_category', 'observed_category',
              'displayed_price', 'reason', 'reason_code', 'suggested_action']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        # Keep portal text as text when opening the CSV in a spreadsheet.
        writer.writerow({k: "'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v
                         for k, v in row.items()})
    escape = lambda value: html.escape(str(value or ''))
    table = []
    for row in rows:
        url = row['property_url']
        link = f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">Open property</a>' if url.startswith(('https://', 'http://')) else 'No saved link'
        values = [escape(row['listing_id']), escape(row['portal']), link,
                  escape(row['saved_category']), escape(row['observed_category']),
                  escape(row['displayed_price']), escape(row['reason']), escape(row['suggested_action'])]
        table.append('<tr>'+''.join('<td>'+v+'</td>' for v in values)+'</tr>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rental recovery: held listings</title><style>
body{font:16px/1.6 Georgia,serif;background:#151515;color:#eee;margin:32px}a,th{color:#c9b18d}
h1{font-weight:normal}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #444}
p{max-width:950px}.table{overflow:auto}input{padding:10px;background:#222;color:#eee;border:1px solid #777;width:300px}
</style><h1>Rental recovery: held listings</h1>'''
    page += f'<p>Updated {escape(generated)}. {len(rows)} held listings. This report is read-only.</p>'
    page += '<p>Open each property and check the billing period beside its main price. If none is stated, leave it unknown. Never assume an ordinary rental is yearly or a short let is daily.</p><p>If the period is now explicit, note the ID and exact wording for a retry. Category changes and links to different properties require separate investigation. You do not need to resolve every hold.</p>'
    page += '<input id="filter" aria-label="Filter listings" placeholder="Filter by ID, portal, or reason"><div class="table"><table><thead><tr>'
    page += ''.join('<th>'+title+'</th>' for title in ['ID', 'Portal', 'Listing', 'Saved category', 'Observed category', 'Displayed price', 'Reason', 'What to do'])
    page += '</tr></thead><tbody>'+''.join(table)+'</tbody></table></div>'
    page += '''<script>document.getElementById('filter').addEventListener('input',function(){const q=this.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script></html>'''
    atomic_write(directory/'manual-review.csv', output.getvalue())
    atomic_write(directory/'manual-review.html', page)
    atomic_write(directory/'manual-review.json', json.dumps(dict(updated_at=generated, held_count=len(rows), listings=rows), indent=2)+'\n')
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path.cwd()/'.local/rental-recovery')
    args = parser.parse_args()
    print(json.dumps(dict(event='review_reports_refreshed', held=export_reviews(args.state_dir), state_dir=str(args.state_dir))))


if __name__ == '__main__':
    main()
