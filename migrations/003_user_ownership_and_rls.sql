-- Migration 003: User ownership columns, Microsoft connections, and RLS policies.
--
-- This migration moves the application from a tenant-scoped model to an
-- individual-user model backed by Supabase Auth (auth.users).
--
-- Changes:
--   1. profiles            – Public profile table keyed to auth.users.
--   2. microsoft_connections – OAuth tokens / connection metadata per user.
--   3. owner_user_id column  – Added to meeting_jobs, meeting_artifacts,
--                              generated_notes, and sharepoint_uploads so that
--                              every user-scoped row is owned by a specific
--                              Supabase auth user.
--   4. RLS policies         – Enabled on all user-scoped tables so that users
--                              can only read and mutate their own rows.
--
-- Notes:
--   * owner_user_id is nullable so existing rows are not broken; application
--     code should always populate it for new rows.
--   * The policies use auth.uid() so they are enforced by Postgres and cannot
--     be bypassed by browser-supplied values.
--   * Service-role connections bypass RLS by default (Supabase behaviour).

-- ---------------------------------------------------------------------------
-- 1. profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profiles (
    id          UUID        PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    email       TEXT,
    display_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  profiles              IS 'Public profile data for each Supabase auth user.';
COMMENT ON COLUMN profiles.id          IS 'Matches auth.users.id (Supabase Auth UUID).';
COMMENT ON COLUMN profiles.email       IS 'Snapshot of the user email; updated on sign-in if changed.';
COMMENT ON COLUMN profiles.display_name IS 'Human-readable name for display in the UI.';

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Users may read and update only their own profile.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_select_own'
    ) THEN
        CREATE POLICY profiles_select_own ON profiles
            FOR SELECT USING (id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_insert_own'
    ) THEN
        CREATE POLICY profiles_insert_own ON profiles
            FOR INSERT WITH CHECK (id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_update_own'
    ) THEN
        CREATE POLICY profiles_update_own ON profiles
            FOR UPDATE USING (id = auth.uid());
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. microsoft_connections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS microsoft_connections (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    microsoft_user_oid  TEXT        NOT NULL,
    email               TEXT,
    display_name        TEXT,
    tenant_id           TEXT,
    access_token        TEXT,
    refresh_token       TEXT,
    token_expires_at    TIMESTAMPTZ,
    scopes              TEXT[],
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_user_id, microsoft_user_oid)
);

COMMENT ON TABLE  microsoft_connections                        IS 'Microsoft OAuth connection metadata per Supabase auth user.';
COMMENT ON COLUMN microsoft_connections.owner_user_id         IS 'Supabase auth.users.id of the owning user.';
COMMENT ON COLUMN microsoft_connections.microsoft_user_oid    IS 'Azure AD Object ID (immutable; used as stable key).';
COMMENT ON COLUMN microsoft_connections.email                 IS 'Microsoft account UPN/email at the time of connection.';
COMMENT ON COLUMN microsoft_connections.display_name          IS 'Microsoft account display name.';
COMMENT ON COLUMN microsoft_connections.tenant_id             IS 'Azure AD tenant GUID.';
COMMENT ON COLUMN microsoft_connections.access_token          IS 'Encrypted OAuth access token.';
COMMENT ON COLUMN microsoft_connections.refresh_token         IS 'Encrypted OAuth refresh token.';
COMMENT ON COLUMN microsoft_connections.token_expires_at      IS 'UTC expiry time for the access token.';
COMMENT ON COLUMN microsoft_connections.scopes                IS 'OAuth scopes granted at the time of connection.';

CREATE INDEX IF NOT EXISTS idx_microsoft_connections_owner ON microsoft_connections (owner_user_id);

ALTER TABLE microsoft_connections ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'microsoft_connections'
          AND policyname = 'microsoft_connections_select_own'
    ) THEN
        CREATE POLICY microsoft_connections_select_own ON microsoft_connections
            FOR SELECT USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'microsoft_connections'
          AND policyname = 'microsoft_connections_insert_own'
    ) THEN
        CREATE POLICY microsoft_connections_insert_own ON microsoft_connections
            FOR INSERT WITH CHECK (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'microsoft_connections'
          AND policyname = 'microsoft_connections_update_own'
    ) THEN
        CREATE POLICY microsoft_connections_update_own ON microsoft_connections
            FOR UPDATE USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'microsoft_connections'
          AND policyname = 'microsoft_connections_delete_own'
    ) THEN
        CREATE POLICY microsoft_connections_delete_own ON microsoft_connections
            FOR DELETE USING (owner_user_id = auth.uid());
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. owner_user_id columns on user-scoped tables
-- ---------------------------------------------------------------------------

-- meeting_jobs
ALTER TABLE meeting_jobs
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL;

COMMENT ON COLUMN meeting_jobs.owner_user_id IS 'Supabase auth.users.id of the user who created this job.';

CREATE INDEX IF NOT EXISTS idx_meeting_jobs_owner_user_id ON meeting_jobs (owner_user_id);

-- meeting_artifacts (ownership is inherited via meeting_jobs; direct column
-- allows RLS policies without a cross-table join)
ALTER TABLE meeting_artifacts
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL;

COMMENT ON COLUMN meeting_artifacts.owner_user_id IS 'Supabase auth.users.id of the user who owns this artifact.';

CREATE INDEX IF NOT EXISTS idx_meeting_artifacts_owner_user_id ON meeting_artifacts (owner_user_id);

-- generated_notes
ALTER TABLE generated_notes
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL;

COMMENT ON COLUMN generated_notes.owner_user_id IS 'Supabase auth.users.id of the user who owns these notes.';

CREATE INDEX IF NOT EXISTS idx_generated_notes_owner_user_id ON generated_notes (owner_user_id);

-- sharepoint_uploads
ALTER TABLE sharepoint_uploads
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL;

COMMENT ON COLUMN sharepoint_uploads.owner_user_id IS 'Supabase auth.users.id of the user who initiated this upload.';

CREATE INDEX IF NOT EXISTS idx_sharepoint_uploads_owner_user_id ON sharepoint_uploads (owner_user_id);

-- ---------------------------------------------------------------------------
-- 4. Enable RLS and add policies for user-scoped tables
-- ---------------------------------------------------------------------------

-- meeting_jobs
ALTER TABLE meeting_jobs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_jobs'
          AND policyname = 'meeting_jobs_select_own'
    ) THEN
        CREATE POLICY meeting_jobs_select_own ON meeting_jobs
            FOR SELECT USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_jobs'
          AND policyname = 'meeting_jobs_insert_own'
    ) THEN
        CREATE POLICY meeting_jobs_insert_own ON meeting_jobs
            FOR INSERT WITH CHECK (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_jobs'
          AND policyname = 'meeting_jobs_update_own'
    ) THEN
        CREATE POLICY meeting_jobs_update_own ON meeting_jobs
            FOR UPDATE USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_jobs'
          AND policyname = 'meeting_jobs_delete_own'
    ) THEN
        CREATE POLICY meeting_jobs_delete_own ON meeting_jobs
            FOR DELETE USING (owner_user_id = auth.uid());
    END IF;
END $$;

-- meeting_artifacts
ALTER TABLE meeting_artifacts ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_artifacts'
          AND policyname = 'meeting_artifacts_select_own'
    ) THEN
        CREATE POLICY meeting_artifacts_select_own ON meeting_artifacts
            FOR SELECT USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_artifacts'
          AND policyname = 'meeting_artifacts_insert_own'
    ) THEN
        CREATE POLICY meeting_artifacts_insert_own ON meeting_artifacts
            FOR INSERT WITH CHECK (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_artifacts'
          AND policyname = 'meeting_artifacts_update_own'
    ) THEN
        CREATE POLICY meeting_artifacts_update_own ON meeting_artifacts
            FOR UPDATE USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'meeting_artifacts'
          AND policyname = 'meeting_artifacts_delete_own'
    ) THEN
        CREATE POLICY meeting_artifacts_delete_own ON meeting_artifacts
            FOR DELETE USING (owner_user_id = auth.uid());
    END IF;
END $$;

-- generated_notes
ALTER TABLE generated_notes ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'generated_notes'
          AND policyname = 'generated_notes_select_own'
    ) THEN
        CREATE POLICY generated_notes_select_own ON generated_notes
            FOR SELECT USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'generated_notes'
          AND policyname = 'generated_notes_insert_own'
    ) THEN
        CREATE POLICY generated_notes_insert_own ON generated_notes
            FOR INSERT WITH CHECK (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'generated_notes'
          AND policyname = 'generated_notes_update_own'
    ) THEN
        CREATE POLICY generated_notes_update_own ON generated_notes
            FOR UPDATE USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'generated_notes'
          AND policyname = 'generated_notes_delete_own'
    ) THEN
        CREATE POLICY generated_notes_delete_own ON generated_notes
            FOR DELETE USING (owner_user_id = auth.uid());
    END IF;
END $$;

-- sharepoint_uploads
ALTER TABLE sharepoint_uploads ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'sharepoint_uploads'
          AND policyname = 'sharepoint_uploads_select_own'
    ) THEN
        CREATE POLICY sharepoint_uploads_select_own ON sharepoint_uploads
            FOR SELECT USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'sharepoint_uploads'
          AND policyname = 'sharepoint_uploads_insert_own'
    ) THEN
        CREATE POLICY sharepoint_uploads_insert_own ON sharepoint_uploads
            FOR INSERT WITH CHECK (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'sharepoint_uploads'
          AND policyname = 'sharepoint_uploads_update_own'
    ) THEN
        CREATE POLICY sharepoint_uploads_update_own ON sharepoint_uploads
            FOR UPDATE USING (owner_user_id = auth.uid());
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'sharepoint_uploads'
          AND policyname = 'sharepoint_uploads_delete_own'
    ) THEN
        CREATE POLICY sharepoint_uploads_delete_own ON sharepoint_uploads
            FOR DELETE USING (owner_user_id = auth.uid());
    END IF;
END $$;
