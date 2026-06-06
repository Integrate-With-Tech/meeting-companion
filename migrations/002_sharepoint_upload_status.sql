-- Migration 002: Expand SharePoint upload tracking for retry-safe auditing.
--
-- Adds status/hash/error columns so failed retries are still persisted and
-- generated note metadata is never dropped when uploads fail.

ALTER TABLE sharepoint_uploads
    ALTER COLUMN sharepoint_item_id DROP NOT NULL;

ALTER TABLE sharepoint_uploads
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS upload_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS error_message TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sharepoint_uploads_upload_status_check'
    ) THEN
        ALTER TABLE sharepoint_uploads
            ADD CONSTRAINT sharepoint_uploads_upload_status_check
            CHECK (upload_status IN ('pending', 'uploaded', 'failed'));
    END IF;
END
$$;

COMMENT ON COLUMN sharepoint_uploads.content_hash IS 'Checksum/hash for uploaded content (Graph-provided or local SHA-256).';
COMMENT ON COLUMN sharepoint_uploads.upload_status IS 'Upload state: pending, uploaded, or failed.';
COMMENT ON COLUMN sharepoint_uploads.error_message IS 'Error details captured when an upload attempt fails.';
