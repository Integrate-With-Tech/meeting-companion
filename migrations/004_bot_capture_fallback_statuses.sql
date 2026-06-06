-- Adds explicit workflow states for future bot/media capture fallback planning.

ALTER TYPE meeting_job_status ADD VALUE IF NOT EXISTS 'scheduled_bot_capture';
ALTER TYPE meeting_job_status ADD VALUE IF NOT EXISTS 'capture_unavailable';

COMMENT ON COLUMN meeting_jobs.status IS
    'Current processing status, including scheduled_bot_capture, capture_unavailable, missing_source_artifact, and authorization_failed.';
