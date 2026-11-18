"""Transactional count storage API; callers own commit/rollback. No listing writes."""
from uuid import UUID
from psycopg2.extras import Json, execute_values
from scraper.property_counts import VERSION,assess_counts,source_hash,extractor_hash


def persist_assessment(conn,listing_id,*,expected_row_version,expected_source_hash,expected_extractor_hash,run_id):
    if conn.autocommit:raise ValueError('Count persistence requires an explicit transaction')
    run_id=str(UUID(str(run_id)))
    fingerprint=extractor_hash()
    if fingerprint!=expected_extractor_hash:
        return dict(outcome='STALE_RULES')
    with conn.cursor() as cur:
        cur.execute('SELECT title,description,xmin::text,source,external_id,property_type_raw FROM raw_data.scraped_listings WHERE id=%s FOR SHARE',(listing_id,))
        row=cur.fetchone()
        if row is None:return dict(outcome='MISSING')
        title,description,row_version,source,external_id,raw_type=row
        if row_version!=expected_row_version or source_hash(title,description,raw_type)!=expected_source_hash:
            return dict(outcome='STALE_SOURCE')
        result=assess_counts(title,description,source=source,external_id=external_id,raw_type=raw_type)
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
        if result['observations']:
            rows=[]
            for ordinal,o in enumerate(result['observations']):
                q=o['quantity']
                rows.append((assessment_id,ordinal,o['entity'],q['kind'],q['minimum'],q['maximum'],
                    o['relationship'],o['parent_key'],o['offer_key'],Json(o['evidence']),Json(o['review_flags']),o['rule']))
            ids=execute_values(cur,'''INSERT INTO raw_data.property_count_observations
                (assessment_id,ordinal,counted_entity,quantity_kind,quantity_min,quantity_max,
                relationship,parent_key,offer_key,evidence,review_flags,rule) VALUES %s RETURNING id,ordinal''',rows,fetch=True)
            execute_values(cur,'''INSERT INTO raw_data.property_count_decisions(observation_id,decision,reason,run_id)
                VALUES %s''',[(oid,result['observations'][ordinal]['decision'],result['observations'][ordinal]['rule'],run_id) for oid,ordinal in ids])
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


def persist_current(conn, listing_id, *, run_id):
    """Observe locked saved text in the caller's listing transaction; never commit."""
    from scraper import property_facts
    with conn.cursor() as cur:
        cur.execute('SELECT title,description,xmin::text,source,external_id,property_type_raw FROM raw_data.scraped_listings WHERE id=%s FOR SHARE',(listing_id,))
        row=cur.fetchone()
        if row is None:return dict(outcome='MISSING')
        title,description,version,source,external_id,raw_type=row
        digest=source_hash(title,description,raw_type)
        result=persist_assessment(conn,listing_id,expected_row_version=version,expected_source_hash=digest,
            expected_extractor_hash=extractor_hash(),run_id=run_id)
        facts=property_facts.assess_facts(title,description,source=source,external_id=external_id,raw_type=raw_type)
        cur.execute('''INSERT INTO raw_data.property_fact_assessments
            (listing_id,source_hash,extractor_sha256,rule_version,run_id,facts)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (listing_id,digest,property_facts.extractor_hash(),property_facts.VERSION,str(UUID(str(run_id))),Json(facts)))
        return result
