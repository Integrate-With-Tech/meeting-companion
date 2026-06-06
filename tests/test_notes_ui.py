"""
Tests for FastAPI template UI routes in services.notes_ui.
"""

import os
import sys
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notes_ui import NotesUIService, create_app  # noqa: E402


class _FakeUIService:
    def __init__(self):
        self.saved = {}
        self.audit_events = []
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
        self._profiles = {
            "user-1": {"id": "user-1", "email": "alice@example.com", "display_name": "Alice"},
        }
        self._ms_connections = {
            "conn-1": {
                "id": "conn-1",
                "owner_user_id": "user-1",
                "microsoft_user_oid": "ms-oid-1",
                "email": "alice@contoso.com",
                "display_name": "Alice (MS)",
                "tenant_id": "tenant-abc",
            },
        }

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

    def get_user_profile(self, user_id):
        return self._profiles.get(user_id)

    def list_microsoft_connections(self, user_id):
        return [c for c in self._ms_connections.values() if c["owner_user_id"] == user_id]

    def check_microsoft_connected(self, user_id):
        return bool(self.list_microsoft_connections(user_id))

    def disconnect_microsoft(self, user_id, connection_id):
        conn = self._ms_connections.get(connection_id)
        if conn and conn["owner_user_id"] == user_id:
            del self._ms_connections[connection_id]
            return True
        return False

    def _append_audit(self, event):
        self.audit_events.append(event)

    def upsert_user_profile(self, user_id, *, email="", display_name=""):
        if not user_id:
            return None
        self._profiles[user_id] = {"id": user_id, "email": email, "display_name": display_name}
        return self._profiles[user_id]

    def connect_microsoft(
        self,
        user_id,
        *,
        microsoft_user_oid,
        email="",
        display_name="",
        tenant_id="",
        access_token="",
        refresh_token="",
    ):
        if not user_id or not microsoft_user_oid:
            return None
        conn = {
            "id": f"conn-{len(self._ms_connections)+1}",
            "owner_user_id": user_id,
            "microsoft_user_oid": microsoft_user_oid,
            "email": email,
            "display_name": display_name or email,
            "tenant_id": tenant_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
        self._ms_connections[conn["id"]] = conn
        return conn


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


class TestAuthRoutes(unittest.TestCase):
    def setUp(self):
        self.service = _FakeUIService()
        self.client = TestClient(create_app(data_service=self.service))

    def test_sign_in_page_renders(self):
        response = self.client.get("/auth/sign-in")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sign In", response.text)
        self.assertIn("Magic Link", response.text)
        self.assertIn("Social Login", response.text)

    def test_sign_in_distinguishes_product_vs_microsoft_login(self):
        response = self.client.get("/auth/sign-in")
        self.assertIn("separate", response.text.lower())
        self.assertIn("Microsoft", response.text)

    def test_magic_link_post_shows_confirmation(self):
        response = self.client.post("/auth/sign-in/magic-link", data={"email": "test@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("test@example.com", response.text)
        self.assertIn("Magic link sent", response.text)

    def test_social_login_route_accepts_supported_provider(self):
        response = self.client.get("/auth/sign-in/social?provider=google&user_id=user-2&email=u2@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Social Login", response.text)

    def test_social_login_route_rejects_unsupported_provider(self):
        response = self.client.get("/auth/sign-in/social?provider=entra")
        self.assertEqual(response.status_code, 400)

    def test_account_page_shows_profile(self):
        response = self.client.get("/auth/account?user_id=user-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("alice@example.com", response.text)
        self.assertIn("Alice", response.text)

    def test_account_page_shows_microsoft_connection(self):
        response = self.client.get("/auth/account?user_id=user-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Connected", response.text)
        self.assertIn("alice@contoso.com", response.text)
        self.assertIn("Disconnect", response.text)

    def test_account_page_no_microsoft_connection(self):
        response = self.client.get("/auth/account?user_id=user-no-ms")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Not connected", response.text)
        self.assertIn("Connect Microsoft Account", response.text)

    def test_account_page_no_profile_shows_sign_in_link(self):
        response = self.client.get("/auth/account?user_id=unknown-user")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sign in", response.text)

    def test_disconnect_microsoft_removes_connection(self):
        response = self.client.post(
            "/auth/microsoft/disconnect",
            data={"user_id": "user-1", "connection_id": "conn-1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("disconnected successfully", response.text)
        self.assertIn("Not connected", response.text)

    def test_disconnect_microsoft_wrong_user_no_effect(self):
        response = self.client.post(
            "/auth/microsoft/disconnect",
            data={"user_id": "other-user", "connection_id": "conn-1"},
        )
        self.assertEqual(response.status_code, 200)
        # connection still exists for user-1 even after wrong-user attempt
        self.assertIn("conn-1", str(self.service._ms_connections))

    def test_connect_microsoft_route_creates_connection(self):
        response = self.client.get(
            "/auth/microsoft/connect?user_id=user-2&microsoft_user_oid=ms-oid-2&email=user2@contoso.com"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Connected", response.text)
        self.assertIn("user2@contoso.com", response.text)


class TestMicrosoftConnectionGating(unittest.TestCase):
    """Meeting detail and history pages gate Teams/SharePoint on MS connection."""

    def setUp(self):
        self.service = _FakeUIService()
        self.client = TestClient(create_app(data_service=self.service))

    def test_detail_teams_source_no_ms_shows_warning(self):
        # viewer_id with no MS connection; transcript_source is teams_native
        response = self.client.get("/notes/meetings/job-1?tenant_id=t-1&viewer_id=user-no-ms")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Microsoft account required", response.text)

    def test_detail_teams_source_with_ms_no_warning(self):
        response = self.client.get("/notes/meetings/job-1?tenant_id=t-1&viewer_id=user-1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Microsoft account required", response.text)

    def test_detail_sharepoint_section_visible_with_ms(self):
        response = self.client.get("/notes/meetings/job-1?tenant_id=t-1&viewer_id=user-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("contoso.sharepoint.com", response.text)

    def test_detail_sharepoint_section_gated_without_ms(self):
        response = self.client.get("/notes/meetings/job-1?tenant_id=t-1&viewer_id=user-no-ms")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("contoso.sharepoint.com", response.text)
        self.assertIn("Connect a Microsoft account", response.text)

    def test_history_no_ms_shows_connect_banner(self):
        response = self.client.get("/notes/history?viewer_id=user-no-ms")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Microsoft account not connected", response.text)

    def test_history_with_ms_no_connect_banner(self):
        response = self.client.get("/notes/history?viewer_id=user-1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Microsoft account not connected", response.text)


class TestNotesUIMicrosoftServiceMethods(unittest.TestCase):
    """Unit tests for the new service methods on NotesUIService."""

    def setUp(self):
        self.service = _FakeUIService()

    def test_get_user_profile_found(self):
        profile = self.service.get_user_profile("user-1")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["email"], "alice@example.com")

    def test_get_user_profile_not_found(self):
        self.assertIsNone(self.service.get_user_profile("unknown"))

    def test_get_user_profile_empty_id(self):
        self.assertIsNone(self.service.get_user_profile(""))

    def test_list_microsoft_connections_returns_rows(self):
        conns = self.service.list_microsoft_connections("user-1")
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["id"], "conn-1")

    def test_list_microsoft_connections_empty_user(self):
        self.assertEqual(self.service.list_microsoft_connections(""), [])

    def test_check_microsoft_connected_true(self):
        self.assertTrue(self.service.check_microsoft_connected("user-1"))

    def test_check_microsoft_connected_false(self):
        self.assertFalse(self.service.check_microsoft_connected("user-no-ms"))

    def test_disconnect_microsoft_success(self):
        result = self.service.disconnect_microsoft("user-1", "conn-1")
        self.assertTrue(result)
        self.assertFalse(self.service.check_microsoft_connected("user-1"))

    def test_disconnect_microsoft_wrong_user(self):
        result = self.service.disconnect_microsoft("other-user", "conn-1")
        self.assertFalse(result)
        self.assertTrue(self.service.check_microsoft_connected("user-1"))

    def test_disconnect_microsoft_missing_ids(self):
        self.assertFalse(self.service.disconnect_microsoft("", "conn-1"))
        self.assertFalse(self.service.disconnect_microsoft("user-1", ""))


class _AuditSink:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)
        return event


class _JobsStub:
    def __init__(self, by_user=None, by_tenant=None, by_id=None):
        self._by_user = by_user or []
        self._by_tenant = by_tenant or []
        self._by_id = by_id or {}

    def list_by_user(self, owner_user_id, limit=100):
        return list(self._by_user)

    def list_by_tenant(self, tenant_id, limit=100):
        return list(self._by_tenant)

    def get(self, job_id):
        return self._by_id.get(job_id)


class _RowsStub:
    def list_by_job(self, meeting_job_id):
        return []


class TestNotesUIServiceOwnership(unittest.TestCase):
    def _make_service(self):
        service = object.__new__(NotesUIService)
        service._audit = _AuditSink()
        service._notes = _RowsStub()
        service._uploads = _RowsStub()
        service._artifacts = _RowsStub()
        service._group_rows_by_job_id = lambda table_name, job_ids: {}
        return service

    def test_list_notes_filters_non_owner_rows(self):
        service = self._make_service()
        service._jobs = _JobsStub(
            by_user=[
                {"id": "job-1", "owner_user_id": "user-1", "created_at": "2026-06-01", "status": "completed"},
                {"id": "job-2", "owner_user_id": "user-2", "created_at": "2026-06-02", "status": "completed"},
            ]
        )
        rows = service.list_notes(
            tenant_id="t-1",
            viewer_id="user-1",
            is_admin=False,
            filters={},
            limit=20,
        )
        self.assertEqual([row["meeting_job_id"] for row in rows], ["job-1"])

    def test_get_note_detail_denies_non_owner(self):
        service = self._make_service()
        service._jobs = _JobsStub(
            by_id={
                "job-1": {
                    "id": "job-1",
                    "tenant_id": "t-1",
                    "owner_user_id": "user-2",
                    "meeting_id": "meeting-a",
                    "created_at": "2026-06-01T00:00:00+00:00",
                }
            }
        )
        detail = service.get_note_detail(tenant_id="t-1", meeting_job_id="job-1", viewer_id="user-1", is_admin=False)
        self.assertIsNone(detail)


if __name__ == "__main__":
    unittest.main()
