"""
Focused end-to-end workflow coverage for Teams transcript -> AI notes -> SharePoint persistence.
"""

from dataclasses import asdict
from datetime import date
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.meeting_notes import generate_notes_payload  # noqa: E402
from services.notes_storage import SharePointGraphAdapter, persist_generated_notes  # noqa: E402
from services.notes_ui import NotesUIService  # noqa: E402
from services.teams_native import ingest_teams_native_artifacts  # noqa: E402


class _MemoryRepo:
    def __init__(self):
        self.rows = []

    def create(self, row):
        payload = asdict(row)
        if not payload.get("id"):
            payload["id"] = f"row-{len(self.rows)+1}"
        self.rows.append(payload)
        return payload

    def list_by_job(self, meeting_job_id):
        return [row for row in self.rows if row.get("meeting_job_id") == meeting_job_id]


class _AuditRepo:
    def __init__(self):
        self.events = []

    def append(self, event):
        payload = asdict(event)
        self.events.append(payload)
        return payload

    def list_by_resource(self, resource_type, resource_id, limit=50):
        rows = [
            row for row in self.events if row.get("resource_type") == resource_type and row.get("resource_id") == resource_id
        ]
        return rows[:limit]


class _JobsRepo:
    def __init__(self, job):
        self.job = dict(job)
        self.history = []

    def update_status(self, meeting_job_id, status, **kwargs):
        self.history.append({"meeting_job_id": meeting_job_id, "status": status, **kwargs})
        self.job["status"] = status
        self.job.update(kwargs)
        return dict(self.job)

    def get(self, job_id):
        if self.job.get("id") == job_id:
            return dict(self.job)
        return None

    def list_by_user(self, owner_user_id, limit=100):
        if self.job.get("owner_user_id") == owner_user_id:
            return [dict(self.job)]
        return []

    def list_by_tenant(self, tenant_id, limit=100):
        if self.job.get("tenant_id") == tenant_id:
            return [dict(self.job)]
        return []


class _NotesRepo(_MemoryRepo):
    pass


class _FakeGraphClient:
    def __init__(self, *, vtt_content=None, recording_artifacts=None, upload_response=None):
        self._vtt_content = vtt_content
        self._recording_artifacts = list(recording_artifacts or [])
        self._upload_response = dict(upload_response or {})
        self.upload_calls = []

    def get_transcript_vtt(self, meeting_id):
        return self._vtt_content

    def list_recording_artifacts(self, meeting_id):
        return list(self._recording_artifacts)

    def upload_drive_item(self, **kwargs):
        self.upload_calls.append(kwargs)
        return dict(self._upload_response)


class TestWorkflowE2E(unittest.TestCase):
    def test_native_transcript_happy_path_to_notes_and_sharepoint(self):
        vtt_content = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n<v Alex>Agenda: review roadmap\n\n"
            "00:00:03.000 --> 00:00:05.000\nAction item: Maya will send notes.\n\n"
            "00:00:06.000 --> 00:00:08.000\nDecision: ship on Friday.\n"
        )
        graph = _FakeGraphClient(
            vtt_content=vtt_content,
            recording_artifacts=[],
            upload_response={
                "id": "drive-item-1",
                "webUrl": "https://contoso.sharepoint.com/sites/meetings/drive-item-1",
                "lastModifiedDateTime": "2026-06-06T10:00:00+00:00",
                "file": {"hashes": {"sha256Hash": "sp-hash"}},
            },
        )
        jobs_repo = _JobsRepo(
            {
                "id": "job-1",
                "tenant_id": "tenant-1",
                "meeting_id": "meeting-1",
                "owner_user_id": "user-1",
                "created_at": "2026-06-06T09:00:00+00:00",
                "source_type": "teams_native",
                "status": "pending",
            }
        )
        artifacts_repo = _MemoryRepo()
        notes_repo = _NotesRepo()
        uploads_repo = _MemoryRepo()
        audit_repo = _AuditRepo()

        ingest_result = ingest_teams_native_artifacts(
            meeting_id="meeting-1",
            meeting_job_id="job-1",
            tenant_id="tenant-1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs_repo,
            artifacts_repo=artifacts_repo,
            audit_repo=audit_repo,
        )

        self.assertEqual(ingest_result["status"], "completed")
        self.assertEqual(len(ingest_result["segments"]), 3)

        with tempfile.TemporaryDirectory() as tmp:
            transcript_path = Path(tmp) / "meeting.vtt"
            transcript_path.write_text(vtt_content, encoding="utf-8")
            with patch(
                "services.meeting_notes.summarize_text",
                return_value=[
                    "Agenda: review roadmap.",
                    "Action item: Maya will send notes.",
                    "Decision: ship on Friday.",
                ],
            ) as summarize:
                payload = generate_notes_payload(
                    transcript_path=transcript_path,
                    meeting_title="Weekly Sync",
                    summarizer="bart",
                    summary_max=5,
                )
            self.assertEqual(summarize.call_count, 1)

            persist_result = persist_generated_notes(
                meeting_job_id="job-1",
                meeting_date=date.fromisoformat(payload.structured_notes["meeting_date"]),
                meeting_title=payload.title,
                markdown_notes=payload.markdown_notes,
                structured_notes=payload.structured_notes,
                tenant_settings={"sharepoint": {"site_id": "site-1", "drive_id": "drive-1", "folder_path": "Notes"}},
                generated_notes_repo=notes_repo,
                artifacts_repo=artifacts_repo,
                sharepoint_uploads_repo=uploads_repo,
                storage_adapter=SharePointGraphAdapter(graph),
                audit_repo=audit_repo,
                tenant_id="tenant-1",
                owner_user_id="user-1",
                actor_email="user-1@example.com",
            )

        self.assertEqual(len(notes_repo.rows), 1)
        self.assertEqual(len(artifacts_repo.rows), 3)
        self.assertEqual(len(uploads_repo.rows), 2)
        self.assertEqual([row["upload_status"] for row in uploads_repo.rows], ["uploaded", "uploaded"])
        self.assertTrue(all(row["owner_user_id"] == "user-1" for row in uploads_repo.rows))
        self.assertEqual(len(graph.upload_calls), 2)
        self.assertEqual(len(persist_result["downloads"]), 2)
        event_types = [row["event_type"] for row in audit_repo.events]
        self.assertEqual(
            event_types,
            [
                "meeting_job.ingestion_started",
                "meeting_job.transcript_ingested",
                "notes.generated",
                "sharepoint.upload_succeeded",
                "sharepoint.upload_succeeded",
            ],
        )

    def test_missing_source_artifact_and_failed_upload_do_not_silently_lose_state(self):
        graph = _FakeGraphClient(vtt_content=None, recording_artifacts=[])
        jobs_repo = _JobsRepo(
            {
                "id": "job-2",
                "tenant_id": "tenant-1",
                "meeting_id": "meeting-2",
                "owner_user_id": "user-2",
                "created_at": "2026-06-06T09:00:00+00:00",
                "source_type": "teams_native",
                "status": "pending",
            }
        )
        artifacts_repo = _MemoryRepo()
        audit_repo = _AuditRepo()

        ingest_result = ingest_teams_native_artifacts(
            meeting_id="meeting-2",
            meeting_job_id="job-2",
            tenant_id="tenant-1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs_repo,
            artifacts_repo=artifacts_repo,
            audit_repo=audit_repo,
        )

        self.assertEqual(ingest_result["status"], "missing_source_artifact")
        self.assertEqual(len(artifacts_repo.rows), 0)
        self.assertEqual(
            [row["event_type"] for row in audit_repo.events],
            ["meeting_job.ingestion_started", "meeting_job.missing_source_artifact"],
        )

        class _FailingUploadAdapter:
            def upload_text(self, *, destination, filename, text_content, content_type):
                raise RuntimeError(f"upload failed for {filename}")

        notes_repo = _NotesRepo()
        artifact_repo = _MemoryRepo()
        uploads_repo = _MemoryRepo()
        persist_result = persist_generated_notes(
            meeting_job_id="job-2",
            meeting_date=date(2026, 6, 6),
            meeting_title="Ops Review",
            markdown_notes="# Ops Review\n\n## Summary\n- Risk update.\n",
            structured_notes={"meeting_title": "Ops Review", "summary": ["Risk update."]},
            tenant_settings={"sharepoint": {"site_id": "site-1", "drive_id": "drive-1"}},
            generated_notes_repo=notes_repo,
            artifacts_repo=artifact_repo,
            sharepoint_uploads_repo=uploads_repo,
            storage_adapter=_FailingUploadAdapter(),
            audit_repo=audit_repo,
            tenant_id="tenant-1",
            owner_user_id="user-2",
        )

        self.assertEqual(len(notes_repo.rows), 1)
        self.assertEqual(len(artifact_repo.rows), 2)
        self.assertEqual(len(uploads_repo.rows), 2)
        self.assertEqual([row["upload_status"] for row in uploads_repo.rows], ["failed", "failed"])
        self.assertEqual(len(persist_result["downloads"]), 2)


class _RowsRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_by_job(self, meeting_job_id):
        return [row for row in self.rows if row.get("meeting_job_id") == meeting_job_id]


class TestNotesHistoryAuthorization(unittest.TestCase):
    def _make_service(self):
        service = object.__new__(NotesUIService)
        service._client = None
        service._append_audit = lambda event: event
        service._group_rows_by_job_id = lambda table_name, job_ids: {}
        service._notes = _RowsRepo([])
        service._uploads = _RowsRepo([])
        service._artifacts = _RowsRepo([])
        service._audit = _AuditRepo()
        return service

    def test_admin_can_view_all_notes_while_organizer_is_scoped(self):
        service = self._make_service()
        jobs = [
            {
                "id": "job-1",
                "tenant_id": "tenant-1",
                "owner_user_id": "user-1",
                "created_by": "user-1",
                "created_at": "2026-06-01T00:00:00+00:00",
                "status": "completed",
                "source_type": "teams_native",
            },
            {
                "id": "job-2",
                "tenant_id": "tenant-1",
                "owner_user_id": "user-2",
                "created_by": "user-2",
                "created_at": "2026-06-02T00:00:00+00:00",
                "status": "completed",
                "source_type": "uploaded_transcript",
            },
        ]
        service._jobs = _JobsRepo(jobs[0])
        service._jobs.list_by_tenant = lambda tenant_id, limit=100: list(jobs)
        service._jobs.list_by_user = lambda owner_user_id, limit=100: [
            row for row in jobs if row["owner_user_id"] == owner_user_id
        ]

        admin_rows = service.list_notes(
            tenant_id="tenant-1",
            viewer_id="admin-user",
            is_admin=True,
            filters={},
            limit=20,
        )
        organizer_rows = service.list_notes(
            tenant_id="tenant-1",
            viewer_id="user-1",
            is_admin=False,
            filters={},
            limit=20,
        )

        self.assertEqual([row["meeting_job_id"] for row in admin_rows], ["job-1", "job-2"])
        self.assertEqual([row["meeting_job_id"] for row in organizer_rows], ["job-1"])
