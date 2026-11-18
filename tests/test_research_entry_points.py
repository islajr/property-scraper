from pathlib import Path
from uuid import uuid4
from tests.test_pricing_database import pricing_writer,listing,get_row


def test_curated_properties_keep_one_listing_and_field_quality(pricing_writer):
    db=pricing_writer;item=listing(source='research-'+uuid4().hex);db.upsert([item],{})
    raw=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute('SELECT listing_id,stored_bedrooms,stored_bathrooms,bedrooms_status,bathrooms_status,contract_version FROM research.properties WHERE listing_id=%s',(raw['id'],))
        assert c.fetchall()==[(raw['id'],3,2,'KNOWN','KNOWN','property-research-v2')]
        c.execute("SELECT obj_description('raw_data.scraped_listings'::regclass),obj_description('raw_data.property_count_decisions'::regclass)")
        assert all(c.fetchone())


def test_coverage_preserves_field_and_source_denominators(pricing_writer):
    db=pricing_writer;source='coverage-'+uuid4().hex;db.upsert([listing(source=source)],{})
    with db.conn.cursor() as c:
        c.execute('SELECT field,status,listings,populated_values,stale_assessments FROM research.room_count_coverage WHERE source=%s ORDER BY field',(source,))
        assert c.fetchall()==[('bathrooms','KNOWN',1,1,0),('bedrooms','KNOWN',1,1,0)]


def test_replaying_entry_points_preserves_appended_consumer_columns(pricing_writer):
    db=pricing_writer
    try:
        with db.conn.cursor() as c:
            c.execute("SELECT pg_get_viewdef('research.properties'::regclass,true)");definition=c.fetchone()[0].strip().rstrip(';')
            c.execute("CREATE OR REPLACE VIEW research.properties WITH (security_invoker=true) AS SELECT p.*,'future'::text AS later_field FROM ("+definition+') p')
            c.execute(Path('schema/014_research_entry_points.sql').read_text())
            c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='research' AND table_name='properties' AND column_name='later_field'")
            assert c.fetchone()==(1,)
    finally:
        db.conn.rollback()
        with db.conn.cursor() as c:
            c.execute('DROP VIEW research.properties')
            c.execute(Path('schema/014_research_entry_points.sql').read_text())
