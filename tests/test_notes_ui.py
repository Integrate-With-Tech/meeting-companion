"""
Tests for FastAPI template UI routes in services.notes_ui.
"""

import os
import sys
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notes_ui import create_app  # noqa: E402


class _FakeUIService:
    def __init__(self):
        self.saved = {}
        self.notes = [
            {
                "meeting_job_id": "job-1",
                "meeting_title": "Weekly Sync",
                "date": "2026-06-01",
                "organizer": "organizer-a",
                "status": "completed",
                "transcript_source": "teams_native",
                "upload_status": "uploaded",
            },
            {
                "meeting_job_id": "job-2",
                "meeting_title": "Ops Review",
                "date": "2026-06-02",
                "organizer": "organizer-b",
                "status": "failed",
                "transcript_source": "uploaded_transcript",
                "upload_status": "failed",
            },
        ]

    def get_setup_settings(self, tenant_id):
        return self.saved.get(
            tenant_id,
            {
                "graph_client_id": "",
                "graph_tenant_id": "",
                "graph_client_secret": "",
                "sharepoint_site_id": "",
                "sharepoint_drive_id": "",
                "sharepoint_folder_path": "",
                "openai_api_key": "",
                "openai_model": "",
                "supabase_url": "",
                "supabase_key": "",
                "webhook_url": "",
            },
        )

    def save_setup_settings(self, tenant_id, form_values):
        self.saved[tenant_id] = dict(form_values)
        return self.saved[tenant_id]

    def get_readiness_checks(self, tenant_id):
        return [
            {"label": "Graph permissions", "ready": True},
            {"label": "Transcript access", "ready": True},
            {"label": "SharePoint folder access", "ready": False},
            {"label": "OpenAI connectivity", "ready": True},
            {"label": "Supabase connection", "ready": True},
            {"label": "Webhook status", "ready": False},
        ]

    def list_notes(self, *, tenant_id, viewer_id, is_admin, filters, limit=100):
        rows = list(self.notes)
        if filters.get("status"):
            rows = [r for r in rows if r["status"] == filters["status"]]
        if not is_admin and viewer_id:
            rows = [r for r in rows if r["organizer"] == viewer_id]
        return rows

    def get_note_detail(self, *, tenant_id, meeting_job_id, viewer_id, is_admin):
        if meeting_job_id != "job-1":
            return None
        return {
            "meeting_job_id": "job-1",
            "meeting_title": "Weekly Sync",
            "meeting_date": "2026-06-01",
            "agenda": ["Roadmap"],
            "action_items": ["Share draft"],
            "decisions": ["Ship v1"],
            "sharepoint_links": ["https://contoso.sharepoint.com/note.md"],
            "transcript_source": "teams_native",
            "status": "completed",
            "model_name": "gpt-4.1",
            "model_version": "2026-06",
            "prompt_tokens": 120,
            "completion_tokens": 60,
            "audit_status": "events_recorded",
            "artifacts": [],
            "content": "# Weekly Sync\n\n## Agenda\n- Roadmap\n",
            "upload_status": "uploaded",
        }

    def build_download(self, detail, fmt):
        if fmt == "markdown":
            return {
                "filename": "2026-06-01-weekly-sync-notes.md",
                "content": detail["content"],
                "content_type": "text/markdown; charset=utf-8",
            }
        return {
            "filename": "2026-06-01-weekly-sync-notes.json",
            "content": '{\n  "meeting_job_id": "job-1"\n}\n',
            "content_type": "application/json; charset=utf-8",
        }


class TestNotesUIRoutes(unittest.TestCase):
    def setUp(self):
        self.service = _FakeUIService()
        self.client = TestClient(create_app(data_service=self.service))

    def test_admin_setup_and_save(self):
        response = self.client.get("/admin/setup?tenant_id=t-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin Setup", response.text)

        post_response = self.client.post(
            "/admin/setup",
            data={
                "tenant_id": "t-1",
                "graph_client_id": "client-1",
                "graph_tenant_id": "tenant-1",
                "graph_client_secret": "secret-1",
                "sharepoint_site_id": "site-1",
                "sharepoint_drive_id": "drive-1",
                "sharepoint_folder_path": "Meetings",
                "openai_api_key": "sk-test",
                "openai_model": "gpt-4.1",
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "service-key",
                "webhook_url": "https://example.com/webhook",
            },
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertIn("Settings saved.", post_response.text)

    def test_readiness_history_detail_and_download(self):
        readiness = self.client.get("/admin/readiness?tenant_id=t-1")
        self.assertEqual(readiness.status_code, 200)
        self.assertIn("Readiness Checklist", readiness.text)

        history = self.client.get("/notes/history?tenant_id=t-1&status=completed")
        self.assertEqual(history.status_code, 200)
        self.assertIn("Weekly Sync", history.text)
        self.assertNotIn("Ops Review", history.text)

        detail = self.client.get("/notes/meetings/job-1?tenant_id=t-1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Action Items", detail.text)
        self.assertIn("Download Markdown", detail.text)
        self.assertIn("Download JSON", detail.text)

        md_download = self.client.get("/notes/meetings/job-1/download/markdown?tenant_id=t-1")
        self.assertEqual(md_download.status_code, 200)
        self.assertIn("attachment; filename=", md_download.headers["content-disposition"])
        self.assertIn("Weekly Sync", md_download.text)

        json_download = self.client.get("/notes/meetings/job-1/download/json?tenant_id=t-1")
        self.assertEqual(json_download.status_code, 200)
        self.assertIn("application/json", json_download.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
