-- Durable backfill receipts. No listing updates or backfills run here.
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE raw_data.property_classification_history
    ADD COLUMN IF NOT EXISTS applied_row_version TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_property_classification_reversal_once
    ON raw_data.property_classification_history(reverses_id) WHERE reverses_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_property_classification_operation_once
    ON raw_data.property_classification_history(run_id,listing_id)
    WHERE origin IN ('BACKFILL','REVERSAL');

CREATE TABLE IF NOT EXISTS raw_data.property_classification_operations (
    run_id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('APPLY','REVERSE')),
    database_fingerprint TEXT NOT NULL,
    manifest JSONB NOT NULL CHECK (jsonb_typeof(manifest)='object'),
    reverse_of UUID REFERENCES raw_data.property_classification_operations(run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((kind='REVERSE') = (reverse_of IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS raw_data.property_classification_receipts (
    run_id UUID NOT NULL REFERENCES raw_data.property_classification_operations(run_id),
    listing_id BIGINT NOT NULL,
    source TEXT NOT NULL,
    listing_status TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'APPLIED','REVERSED','UNCHANGED','CONCURRENT_CHANGE','MISSING',
        'PROPOSAL_MISMATCH','SUBSEQUENT_CHANGE','ALREADY_REVERSED')),
    history_id BIGINT REFERENCES raw_data.property_classification_history(id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id,listing_id),
    CHECK ((outcome IN ('APPLIED','REVERSED')) = (history_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_property_classification_reverse_of
    ON raw_data.property_classification_operations(reverse_of);
CREATE OR REPLACE FUNCTION raw_data.property_classification_operation_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Classification operations and receipts are append-only';
END $$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='property_classification_operation_immutable'
                   AND tgrelid='raw_data.property_classification_operations'::regclass) THEN
        CREATE TRIGGER property_classification_operation_immutable
            BEFORE UPDATE OR DELETE ON raw_data.property_classification_operations
            FOR EACH ROW EXECUTE FUNCTION raw_data.property_classification_operation_immutable();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='property_classification_receipt_immutable'
                   AND tgrelid='raw_data.property_classification_receipts'::regclass) THEN
        CREATE TRIGGER property_classification_receipt_immutable
            BEFORE UPDATE OR DELETE ON raw_data.property_classification_receipts
            FOR EACH ROW EXECUTE FUNCTION raw_data.property_classification_operation_immutable();
    END IF;
END $$;
COMMIT;
