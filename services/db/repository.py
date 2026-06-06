"""
Repository layer for Supabase/Postgres access.

Each class encapsulates all database operations for a single table.
Repositories accept a Supabase ``Client`` (or any compatible object that
implements ``.table(name)`` returning a query builder) so that tests can
inject a lightweight mock without a live database connection.

Usage::

    from services.db import get_client
    from services.db.repository import (
        MeetingJobRepository,
        GeneratedNotesRepository,
        AuditEventRepository,
    )

    client = get_client()
    jobs   = MeetingJobRepository(client)
    job    = jobs.create(tenant_id="abc123", source_type="teams_native")
    jobs.update_status(job["id"], "completed")

Design rules
------------
- All methods return plain ``dict`` rows as returned by Supabase (or raise).
- ``AuditEventRepository`` exposes only :meth:`~AuditEventRepository.append`;
  no update or delete is provided to enforce the append-only contract.
- ``ValueError`` is raised for unknown enum values before hitting the DB.
"""

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from services.db.models import (
    MEETING_JOB_STATUSES,
    MEETING_SOURCE_TYPES,
    AuditEvent,
    GeneratedNotes,
    MeetingArtifact,
    MeetingJob,
    SharePointUpload,
    TenantSettings,
    UserIdentity,
)


def _strip_nones(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *d* with all ``None``-valued keys removed."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# TenantSettingsRepository
# ---------------------------------------------------------------------------


class TenantSettingsRepository:
    """CRUD operations for the ``tenant_settings`` table."""

    TABLE = "tenant_settings"

    def __init__(self, client: Any) -> None:
        self._client = client

    def upsert(self, settings: TenantSettings) -> Dict[str, Any]:
        """Insert or update a tenant settings row.

        Uses ``tenant_id`` as the conflict target so that callers can call
        this method without knowing whether a row already exists.
        """
        payload = _strip_nones(asdict(settings))
        result = self._client.table(self.TABLE).upsert(payload, on_conflict="tenant_id").execute()
        return result.data[0]

    def get_by_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Return the settings row for *tenant_id*, or ``None`` if absent."""
        result = self._client.table(self.TABLE).select("*").eq("tenant_id", tenant_id).maybe_single().execute()
        return result.data


# ---------------------------------------------------------------------------
# UserIdentityRepository
# ---------------------------------------------------------------------------


class UserIdentityRepository:
    """CRUD operations for the ``user_identities`` table."""

    TABLE = "user_identities"

    def __init__(self, client: Any) -> None:
        self._client = client

    def upsert(self, identity: UserIdentity) -> Dict[str, Any]:
        """Insert or update a user identity row.

        Uses ``(tenant_id, user_oid)`` as the conflict target.
        """
        payload = _strip_nones(asdict(identity))
        result = self._client.table(self.TABLE).upsert(payload, on_conflict="tenant_id,user_oid").execute()
        return result.data[0]

    def get_by_oid(self, tenant_id: str, user_oid: str) -> Optional[Dict[str, Any]]:
        """Return the identity row for *(tenant_id, user_oid)*, or ``None``."""
        result = (
            self._client.table(self.TABLE)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("user_oid", user_oid)
            .maybe_single()
            .execute()
        )
        return result.data

    def list_by_tenant(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Return all identity rows for a tenant."""
        result = self._client.table(self.TABLE).select("*").eq("tenant_id", tenant_id).execute()
        return result.data


# ---------------------------------------------------------------------------
# MeetingJobRepository
# ---------------------------------------------------------------------------


class MeetingJobRepository:
    """CRUD operations for the ``meeting_jobs`` table."""

    TABLE = "meeting_jobs"

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, job: MeetingJob) -> Dict[str, Any]:
        """Insert a new meeting job row and return the created record.

        Raises
        ------
        ValueError
            If ``job.source_type`` or ``job.status`` is not a recognised enum
            value.
        """
        if job.source_type not in MEETING_SOURCE_TYPES:
            raise ValueError(f"Unknown source_type {job.source_type!r}. Must be one of: {sorted(MEETING_SOURCE_TYPES)}")
        if job.status not in MEETING_JOB_STATUSES:
            raise ValueError(f"Unknown status {job.status!r}. Must be one of: {sorted(MEETING_JOB_STATUSES)}")
        payload = _strip_nones(asdict(job))
        result = self._client.table(self.TABLE).insert(payload).execute()
        return result.data[0]

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the job row for *job_id*, or ``None`` if not found."""
        result = self._client.table(self.TABLE).select("*").eq("id", job_id).maybe_single().execute()
        return result.data

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: Optional[str] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update the processing status (and optional metadata) of a job.

        Raises
        ------
        ValueError
            If *status* is not a recognised value.
        """
        if status not in MEETING_JOB_STATUSES:
            raise ValueError(f"Unknown status {status!r}. Must be one of: {sorted(MEETING_JOB_STATUSES)}")
        patch: Dict[str, Any] = {"status": status}
        if error_message is not None:
            patch["error_message"] = error_message
        if model_name is not None:
            patch["model_name"] = model_name
        if model_version is not None:
            patch["model_version"] = model_version
        if input_tokens is not None:
            patch["input_tokens"] = input_tokens
        if output_tokens is not None:
            patch["output_tokens"] = output_tokens
        result = self._client.table(self.TABLE).update(patch).eq("id", job_id).execute()
        return result.data[0]

    def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return meeting jobs for *tenant_id*, optionally filtered by *status*."""
        query = (
            self._client.table(self.TABLE).select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).limit(limit)
        )
        if status is not None:
            if status not in MEETING_JOB_STATUSES:
                raise ValueError(f"Unknown status {status!r}. Must be one of: {sorted(MEETING_JOB_STATUSES)}")
            query = query.eq("status", status)
        return query.execute().data


# ---------------------------------------------------------------------------
# MeetingArtifactRepository
# ---------------------------------------------------------------------------


class MeetingArtifactRepository:
    """CRUD operations for the ``meeting_artifacts`` table."""

    TABLE = "meeting_artifacts"

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, artifact: MeetingArtifact) -> Dict[str, Any]:
        """Insert a new artifact row and return the created record."""
        payload = _strip_nones(asdict(artifact))
        result = self._client.table(self.TABLE).insert(payload).execute()
        return result.data[0]

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Return the artifact row for *artifact_id*, or ``None``."""
        result = self._client.table(self.TABLE).select("*").eq("id", artifact_id).maybe_single().execute()
        return result.data

    def list_by_job(self, meeting_job_id: str) -> List[Dict[str, Any]]:
        """Return all artifact rows for a meeting job."""
        result = self._client.table(self.TABLE).select("*").eq("meeting_job_id", meeting_job_id).execute()
        return result.data


# ---------------------------------------------------------------------------
# GeneratedNotesRepository
# ---------------------------------------------------------------------------


class GeneratedNotesRepository:
    """CRUD operations for the ``generated_notes`` table."""

    TABLE = "generated_notes"

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, notes: GeneratedNotes) -> Dict[str, Any]:
        """Insert a new generated-notes row and return the created record."""
        payload = _strip_nones(asdict(notes))
        result = self._client.table(self.TABLE).insert(payload).execute()
        return result.data[0]

    def update_content(
        self,
        notes_id: str,
        content: str,
        *,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update the note content (and optional token counts)."""
        patch: Dict[str, Any] = {"content": content}
        if prompt_tokens is not None:
            patch["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            patch["completion_tokens"] = completion_tokens
        result = self._client.table(self.TABLE).update(patch).eq("id", notes_id).execute()
        return result.data[0]

    def get(self, notes_id: str) -> Optional[Dict[str, Any]]:
        """Return the notes row for *notes_id*, or ``None``."""
        result = self._client.table(self.TABLE).select("*").eq("id", notes_id).maybe_single().execute()
        return result.data

    def list_by_job(self, meeting_job_id: str) -> List[Dict[str, Any]]:
        """Return all notes rows for a meeting job."""
        result = self._client.table(self.TABLE).select("*").eq("meeting_job_id", meeting_job_id).execute()
        return result.data


# ---------------------------------------------------------------------------
# SharePointUploadRepository
# ---------------------------------------------------------------------------


class SharePointUploadRepository:
    """CRUD operations for the ``sharepoint_uploads`` table."""

    TABLE = "sharepoint_uploads"

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, upload: SharePointUpload) -> Dict[str, Any]:
        """Insert a new SharePoint upload record and return it."""
        payload = _strip_nones(asdict(upload))
        result = self._client.table(self.TABLE).insert(payload).execute()
        return result.data[0]

    def get(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Return the upload row for *upload_id*, or ``None``."""
        result = self._client.table(self.TABLE).select("*").eq("id", upload_id).maybe_single().execute()
        return result.data

    def list_by_job(self, meeting_job_id: str) -> List[Dict[str, Any]]:
        """Return all upload rows for a meeting job."""
        result = self._client.table(self.TABLE).select("*").eq("meeting_job_id", meeting_job_id).execute()
        return result.data


# ---------------------------------------------------------------------------
# AuditEventRepository  (append-only)
# ---------------------------------------------------------------------------


class AuditEventRepository:
    """Append-only operations for the ``audit_events`` table.

    Deliberately exposes **only** :meth:`append` and :meth:`list_by_resource`
    to reinforce the invariant that audit records are never modified.
    """

    TABLE = "audit_events"

    def __init__(self, client: Any) -> None:
        self._client = client

    def append(self, event: AuditEvent) -> Dict[str, Any]:
        """Insert a new audit event and return the persisted record.

        This is the **only** write method available on this repository.
        """
        payload = _strip_nones(asdict(event))
        result = self._client.table(self.TABLE).insert(payload).execute()
        return result.data[0]

    def list_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        *,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return audit events for a specific resource, oldest first."""
        result = (
            self._client.table(self.TABLE)
            .select("*")
            .eq("resource_type", resource_type)
            .eq("resource_id", resource_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data

    def list_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return the most-recent audit events for a tenant."""
        result = (
            self._client.table(self.TABLE)
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
