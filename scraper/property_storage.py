"""Classification persistence within the caller's existing transaction."""
from dataclasses import asdict
import json
from uuid import uuid4
from psycopg2.extras import Json
from scraper.property_types import FIELDS, classify, metadata, decision_key


def ensure_classification(listing):
    """Old DTO/checkpoint values are unreviewed, not supporting raw evidence."""
    if listing.property_type_status == 'LEGACY_UNREVIEWED':
        result = classify(listing.property_type_raw, listing.title, listing.description,
                          listing.property_type_raw_source)
        for name, value in asdict(result).items():
            setattr(listing, name, value)
    return listing


def persist(cur, listing_id, previous, listing, origin, run_id=None):
    """Save a decision and its before/after audit atomically; never commit here.

    Identical decisions retain their original classification time and do not
    emit duplicate history. Callers must lock existing rows before comparison.
    """
    new = metadata(ensure_classification(listing))
    if previous is not None and decision_key(previous) == decision_key(new):
        return False
    values = {**new, 'id': listing_id,
              'property_type_evidence': Json(new['property_type_evidence'])}
    cur.execute('UPDATE raw_data.scraped_listings SET ' +
                ', '.join(f'{name}=%({name})s' for name in FIELDS) + ' WHERE id=%(id)s', values)
    encode = lambda data: Json(data, dumps=lambda item: json.dumps(item, default=str))
    cur.execute('''INSERT INTO raw_data.property_classification_history
        (listing_id,run_id,origin,old_classification,new_classification)
        VALUES (%s,%s,%s,%s,%s)''',
        (listing_id, run_id or str(uuid4()), origin,
         encode(metadata(previous)) if previous is not None else None, encode(new)))
    return True
