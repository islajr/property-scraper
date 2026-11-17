"""Transactional count storage API; callers own commit/rollback. No listing writes."""
from uuid import UUID
from psycopg2.extras import Json
from scraper.property_counts import VERSION,assess_counts,source_hash,extractor_hash


def persist_assessment(conn,listing_id,*,expected_row_version,expected_source_hash,expected_extractor_hash,run_id):
    if conn.autocommit:raise ValueError('Count persistence requires an explicit transaction')
    run_id=str(UUID(str(run_id)))
    fingerprint=extractor_hash()
    if fingerprint!=expected_extractor_hash:
        return dict(outcome='STALE_RULES')
    with conn.cursor() as cur:
        cur.execute('SELECT title,description,xmin::text FROM raw_data.scraped_listings WHERE id=%s FOR SHARE',(listing_id,))
        row=cur.fetchone()
        if row is None:return dict(outcome='MISSING')
        title,description,row_version=row
        if row_version!=expected_row_version or source_hash(title,description)!=expected_source_hash:
            return dict(outcome='STALE_SOURCE')
        result=assess_counts(title,description)
        cur.execute('''INSERT INTO raw_data.property_count_assessments
            (listing_id,rule_version,extractor_sha256,source_hash,source_row_version,run_id,state,questions)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id''',
            (listing_id,VERSION,fingerprint,result['source_hash'],row_version,run_id,result['state'],Json(result['questions'])))
        created=cur.fetchone()
        if created is None:
            cur.execute('''SELECT id FROM raw_data.property_count_assessments
                WHERE listing_id=%s AND rule_version=%s AND extractor_sha256=%s AND source_hash=%s''',
                (listing_id,VERSION,fingerprint,result['source_hash']))
            return dict(outcome='ALREADY_ASSESSED',assessment_id=cur.fetchone()[0])
        assessment_id=created[0]
        for ordinal,o in enumerate(result['observations']):
            q=o['quantity']
            cur.execute('''INSERT INTO raw_data.property_count_observations
                (assessment_id,ordinal,counted_entity,quantity_kind,quantity_min,quantity_max,
                 relationship,parent_key,offer_key,evidence,review_flags,rule)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (assessment_id,ordinal,o['entity'],q['kind'],q['minimum'],q['maximum'],o['relationship'],
                 o['parent_key'],o['offer_key'],Json(o['evidence']),Json(o['review_flags']),o['rule']))
            observation_id=cur.fetchone()[0]
            cur.execute('''INSERT INTO raw_data.property_count_decisions(observation_id,decision,reason,run_id)
                VALUES (%s,%s,%s,%s)''',(observation_id,o['decision'],o['rule'],run_id))
        return dict(outcome='STORED',assessment_id=assessment_id,observations=len(result['observations']))


def revoke_assessment(conn,assessment_id,*,expected_run_id,run_id,reason):
    """Append reversals only for decisions still owned by the specified run."""
    if conn.autocommit:raise ValueError('Count reversal requires an explicit transaction')
    expected_run_id,run_id=str(UUID(str(expected_run_id))),str(UUID(str(run_id)))
    if not reason.strip():raise ValueError('A reversal reason is required')
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM raw_data.property_count_assessments WHERE id=%s FOR UPDATE',(assessment_id,))
        if not cur.fetchone():return 0
        cur.execute('''SELECT d.observation_id,d.decision,d.run_id::text FROM
            (SELECT DISTINCT ON (d.observation_id) d.* FROM raw_data.property_count_decisions d
             JOIN raw_data.property_count_observations o ON o.id=d.observation_id
             WHERE o.assessment_id=%s ORDER BY d.observation_id,d.id DESC) d''',(assessment_id,))
        latest=cur.fetchall();count=0
        for observation_id,decision,owner in latest:
            if owner!=expected_run_id or decision=='REVOKE':continue
            cur.execute('''INSERT INTO raw_data.property_count_decisions(observation_id,decision,reason,run_id)
                VALUES (%s,'REVOKE',%s,%s)''',(observation_id,reason,run_id));count+=1
        return count
