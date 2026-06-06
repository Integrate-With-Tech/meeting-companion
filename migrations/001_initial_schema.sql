-- Migration 001: Initial schema for Supabase Postgres
-- Creates all tables required for meeting transcription metadata.
--
-- Tables:
--   tenant_settings    – Per-tenant configuration key/value store.
--   user_identities    – Azure AD / provider identity mapping per tenant.
--   meeting_jobs       – One row per meeting processing job.
--   meeting_artifacts  – Output files produced by a meeting job.
--   generated_notes    – AI-generated notes/summaries for a meeting job.
--   sharepoint_uploads – SharePoint item tracking for uploaded artifacts.
--   audit_events       – Append-only audit log (application writes only).
--
-- Design notes:
--   * All primary keys use gen_random_uuid() (Postgres 13+ / pgcrypto).
--   * Timestamps are stored as TIMESTAMPTZ (UTC).
--   * The audit_events table intentionally has no UPDATE or DELETE triggers;
--     application code must treat it as append-only.
--   * Row-Level Security (RLS) is NOT enabled here; enable per-tenant
--     policies in a subsequent migration once auth is wired up.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- tenant_settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_settings (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      TEXT        NOT NULL UNIQUE,
    settings       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  tenant_settings             IS 'Per-tenant configuration key/value store.';
COMMENT ON COLUMN tenant_settings.tenant_id   IS 'Azure AD tenant GUID or slug.';
COMMENT ON COLUMN tenant_settings.settings    IS 'Freeform JSON configuration blob.';

-- ---------------------------------------------------------------------------
-- user_identities
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_identities (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      TEXT        NOT NULL,
    user_oid       TEXT        NOT NULL,
    email          TEXT,
    display_name   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_oid)
);

COMMENT ON TABLE  user_identities            IS 'Maps provider identity (Azure AD OID) to application user.';
COMMENT ON COLUMN user_identities.user_oid   IS 'Azure AD Object ID (immutable, used as stable key).';
COMMENT ON COLUMN user_identities.email      IS 'Current UPN/email; may change, stored for display only.';

CREATE INDEX IF NOT EXISTS idx_user_identities_tenant_id ON user_identities (tenant_id);

-- ---------------------------------------------------------------------------
-- meeting_jobs
-- ---------------------------------------------------------------------------
CREATE TYPE IF NOT EXISTS meeting_source_type AS ENUM (
    'teams_native',
    'uploaded_media',
    'uploaded_transcript',
    'bot_capture'
);

CREATE TYPE IF NOT EXISTS meeting_job_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'missing_source_artifact'
);

CREATE TABLE IF NOT EXISTS meeting_jobs (
    id                UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         TEXT                NOT NULL,
    meeting_id        TEXT,
    source_type       meeting_source_type NOT NULL DEFAULT 'teams_native',
    status            meeting_job_status  NOT NULL DEFAULT 'pending',
    model_name        TEXT,
    model_version     TEXT,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    error_message     TEXT,
    created_by        UUID                REFERENCES user_identities (id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  meeting_jobs                     IS 'One row per meeting transcription/processing job.';
COMMENT ON COLUMN meeting_jobs.meeting_id          IS 'Microsoft Teams meeting ID (nullable for uploaded artifacts).';
COMMENT ON COLUMN meeting_jobs.source_type         IS 'Origin of the audio/transcript data.';
COMMENT ON COLUMN meeting_jobs.status              IS 'Current processing status, including missing_source_artifact.';
COMMENT ON COLUMN meeting_jobs.model_name          IS 'Whisper model name used for transcription (e.g. large-v3).';
COMMENT ON COLUMN meeting_jobs.model_version       IS 'Model version string or checkpoint hash.';
COMMENT ON COLUMN meeting_jobs.input_tokens        IS 'Summarisation model input token count.';
COMMENT ON COLUMN meeting_jobs.output_tokens       IS 'Summarisation model output token count.';
COMMENT ON COLUMN meeting_jobs.error_message       IS 'Human-readable error detail when status = failed.';

CREATE INDEX IF NOT EXISTS idx_meeting_jobs_tenant_id  ON meeting_jobs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_meeting_jobs_status     ON meeting_jobs (status);
CREATE INDEX IF NOT EXISTS idx_meeting_jobs_created_at ON meeting_jobs (created_at);

-- ---------------------------------------------------------------------------
-- meeting_artifacts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meeting_artifacts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_job_id  UUID        NOT NULL REFERENCES meeting_jobs (id) ON DELETE CASCADE,
    artifact_type   TEXT        NOT NULL,
    storage_path    TEXT        NOT NULL,
    checksum        TEXT,
    size_bytes      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  meeting_artifacts                   IS 'Output files produced by a meeting job.';
COMMENT ON COLUMN meeting_artifacts.artifact_type     IS 'E.g. transcript, captions_srt, captions_vtt, full_text.';
COMMENT ON COLUMN meeting_artifacts.storage_path      IS 'Relative or absolute storage path / object key.';
COMMENT ON COLUMN meeting_artifacts.checksum          IS 'SHA-256 hex digest of the artifact content.';
COMMENT ON COLUMN meeting_artifacts.size_bytes        IS 'Artifact file size in bytes.';

CREATE INDEX IF NOT EXISTS idx_meeting_artifacts_job_id ON meeting_artifacts (meeting_job_id);

-- ---------------------------------------------------------------------------
-- generated_notes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generated_notes (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_job_id   UUID        NOT NULL REFERENCES meeting_jobs (id) ON DELETE CASCADE,
    model_name       TEXT,
    model_version    TEXT,
    prompt_tokens    INTEGER,
    completion_tokens INTEGER,
    content          TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  generated_notes                        IS 'AI-generated summaries/notes for a meeting job.';
COMMENT ON COLUMN generated_notes.model_name             IS 'Summarisation model name (e.g. facebook/bart-large-cnn).';
COMMENT ON COLUMN generated_notes.model_version          IS 'Model version or checkpoint identifier.';
COMMENT ON COLUMN generated_notes.prompt_tokens          IS 'Number of tokens in the summarisation prompt.';
COMMENT ON COLUMN generated_notes.completion_tokens      IS 'Number of tokens in the generated output.';
COMMENT ON COLUMN generated_notes.content                IS 'The full generated notes/summary text.';

CREATE INDEX IF NOT EXISTS idx_generated_notes_job_id ON generated_notes (meeting_job_id);

-- ---------------------------------------------------------------------------
-- sharepoint_uploads
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sharepoint_uploads (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_job_id      UUID        NOT NULL REFERENCES meeting_jobs (id) ON DELETE CASCADE,
    artifact_id         UUID        REFERENCES meeting_artifacts (id) ON DELETE SET NULL,
    sharepoint_item_id  TEXT        NOT NULL,
    web_url             TEXT,
    drive_id            TEXT,
    site_id             TEXT,
    uploaded_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  sharepoint_uploads                         IS 'Tracks artifacts uploaded to SharePoint.';
COMMENT ON COLUMN sharepoint_uploads.sharepoint_item_id      IS 'SharePoint Drive Item ID returned by the Graph API.';
COMMENT ON COLUMN sharepoint_uploads.web_url                 IS 'Browser-accessible URL of the SharePoint item.';
COMMENT ON COLUMN sharepoint_uploads.drive_id                IS 'Graph API Drive ID containing the item.';
COMMENT ON COLUMN sharepoint_uploads.site_id                 IS 'Graph API Site ID containing the drive.';
COMMENT ON COLUMN sharepoint_uploads.uploaded_at             IS 'Timestamp when the upload was confirmed by the API.';

CREATE INDEX IF NOT EXISTS idx_sharepoint_uploads_job_id ON sharepoint_uploads (meeting_job_id);

-- ---------------------------------------------------------------------------
-- audit_events  (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_events (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type     TEXT        NOT NULL,
    actor_id       UUID,
    actor_email    TEXT,
    tenant_id      TEXT,
    resource_type  TEXT,
    resource_id    TEXT,
    metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  audit_events              IS 'Append-only audit log; application code must never UPDATE or DELETE rows.';
COMMENT ON COLUMN audit_events.event_type   IS 'Namespaced event name, e.g. meeting_job.created, notes.generated.';
COMMENT ON COLUMN audit_events.actor_id     IS 'user_identities.id of the acting user (nullable for system events).';
COMMENT ON COLUMN audit_events.actor_email  IS 'Snapshot of actor email at the time of the event.';
COMMENT ON COLUMN audit_events.resource_type IS 'Entity type affected, e.g. meeting_job, generated_notes.';
COMMENT ON COLUMN audit_events.resource_id   IS 'UUID (as text) of the affected resource.';
COMMENT ON COLUMN audit_events.metadata      IS 'Additional event-specific context.';

CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_id    ON audit_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_resource     ON audit_events (resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at   ON audit_events (created_at);
