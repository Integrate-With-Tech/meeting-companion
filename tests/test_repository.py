"""
Tests for services.db – the Supabase repository layer.

All tests use an in-process mock client so that no live database connection
is required.  The mock replicates the Supabase Python SDK's fluent query
builder interface (``table().select().eq().execute()``) and returns
``SimpleNamespace`` objects whose ``.data`` attribute contains the expected
rows.
"""

import types
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db.models import (
    AuditEvent,
    GeneratedNotes,
    MeetingArtifact,
    MeetingJob,
    MicrosoftConnection,
    SharePointUpload,
    TenantSettings,
    UserIdentity,
    UserProfile,
)
from services.db.repository import (
    AuditEventRepository,
    GeneratedNotesRepository,
    MeetingArtifactRepository,
    MeetingJobRepository,
    MicrosoftConnectionRepository,
    SharePointUploadRepository,
    TenantSettingsRepository,
    UserIdentityRepository,
    UserProfileRepository,
    _strip_nones,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data):
    """Return a SimpleNamespace that looks like a successful Supabase result."""
    return types.SimpleNamespace(data=data)


def _mock_client(return_row=None):
    """Build a minimal mock of the Supabase client's fluent query builder.

    Every method in the chain (table, select, insert, update, upsert, eq,
    order, limit, maybe_single) returns the same mock so that arbitrary
    chains like ``.table().insert().execute()`` work without explicit setup.
    """
    client = MagicMock()
    # Make every attribute access return the same mock (fluent interface)
    chain = MagicMock()
    chain.execute.return_value = _ok([return_row] if return_row is not None else [])
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.upsert.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.maybe_single.return_value = chain
    client.table.return_value = chain
    return client, chain


# ---------------------------------------------------------------------------
# _strip_nones
# ---------------------------------------------------------------------------


class TestStripNones(unittest.TestCase):
    def test_removes_none_values(self):
        self.assertEqual(_strip_nones({"a": 1, "b": None, "c": "x"}), {"a": 1, "c": "x"})

    def test_empty_dict(self):
        self.assertEqual(_strip_nones({}), {})

    def test_no_nones(self):
        d = {"x": 0, "y": False, "z": ""}
        self.assertEqual(_strip_nones(d), d)


# ---------------------------------------------------------------------------
# TenantSettingsRepository
# ---------------------------------------------------------------------------


class TestTenantSettingsRepository(unittest.TestCase):

    def test_upsert_returns_row(self):
        row = {"id": "uuid-1", "tenant_id": "t1", "settings": {}}
        client, chain = _mock_client(row)
        repo = TenantSettingsRepository(client)
        result = repo.upsert(TenantSettings(tenant_id="t1"))
        self.assertEqual(result["tenant_id"], "t1")
        chain.upsert.assert_called_once()

    def test_get_by_tenant_returns_data(self):
        row = {"id": "uuid-1", "tenant_id": "t1", "settings": {"key": "val"}}
        client, chain = _mock_client(row)
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _ok(row)
        repo = TenantSettingsRepository(client)
        result = repo.get_by_tenant("t1")
        self.assertEqual(result["tenant_id"], "t1")


# ---------------------------------------------------------------------------
# UserIdentityRepository
# ---------------------------------------------------------------------------


class TestUserIdentityRepository(unittest.TestCase):

    def test_upsert_returns_row(self):
        row = {"id": "uid-1", "tenant_id": "t1", "user_oid": "oid-1"}
        client, chain = _mock_client(row)
        repo = UserIdentityRepository(client)
        result = repo.upsert(UserIdentity(tenant_id="t1", user_oid="oid-1"))
        self.assertEqual(result["user_oid"], "oid-1")

    def test_get_by_oid_returns_data(self):
        row = {"id": "uid-1", "tenant_id": "t1", "user_oid": "oid-1"}
        client, chain = _mock_client(row)
        chain.execute.return_value = _ok(row)
        repo = UserIdentityRepository(client)
        result = repo.get_by_oid("t1", "oid-1")
        self.assertEqual(result["user_oid"], "oid-1")

    def test_list_by_tenant_returns_list(self):
        rows = [{"id": "uid-1"}, {"id": "uid-2"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = UserIdentityRepository(client)
        result = repo.list_by_tenant("t1")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# MeetingJobRepository
# ---------------------------------------------------------------------------


class TestMeetingJobRepository(unittest.TestCase):

    def _make_row(self, **overrides):
        base = {
            "id": "job-1",
            "tenant_id": "t1",
            "source_type": "teams_native",
            "status": "pending",
        }
        base.update(overrides)
        return base

    def test_create_returns_row(self):
        row = self._make_row()
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.create(MeetingJob(tenant_id="t1", source_type="teams_native"))
        self.assertEqual(result["id"], "job-1")

    def test_create_invalid_source_type_raises(self):
        client, _ = _mock_client()
        repo = MeetingJobRepository(client)
        with self.assertRaises(ValueError):
            repo.create(MeetingJob(tenant_id="t1", source_type="bad_type"))

    def test_create_invalid_status_raises(self):
        client, _ = _mock_client()
        repo = MeetingJobRepository(client)
        with self.assertRaises(ValueError):
            repo.create(MeetingJob(tenant_id="t1", source_type="teams_native", status="bad_status"))

    def test_create_missing_source_artifact_status(self):
        """missing_source_artifact must be accepted as a valid status."""
        row = self._make_row(status="missing_source_artifact")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.create(MeetingJob(tenant_id="t1", source_type="teams_native", status="missing_source_artifact"))
        self.assertEqual(result["status"], "missing_source_artifact")

    def test_create_authorization_failed_status(self):
        row = self._make_row(status="authorization_failed")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.create(MeetingJob(tenant_id="t1", source_type="teams_native", status="authorization_failed"))
        self.assertEqual(result["status"], "authorization_failed")

    def test_create_scheduled_bot_capture_status(self):
        row = self._make_row(status="scheduled_bot_capture")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.create(MeetingJob(tenant_id="t1", source_type="bot_capture", status="scheduled_bot_capture"))
        self.assertEqual(result["status"], "scheduled_bot_capture")

    def test_create_capture_unavailable_status(self):
        row = self._make_row(status="capture_unavailable")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.create(MeetingJob(tenant_id="t1", source_type="bot_capture", status="capture_unavailable"))
        self.assertEqual(result["status"], "capture_unavailable")

    def test_update_status_builds_correct_patch(self):
        row = self._make_row(status="completed")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        repo.update_status("job-1", "completed", model_name="large-v3", input_tokens=512, output_tokens=128)
        chain.update.assert_called_once()
        patch_arg = chain.update.call_args[0][0]
        self.assertEqual(patch_arg["status"], "completed")
        self.assertEqual(patch_arg["model_name"], "large-v3")
        self.assertEqual(patch_arg["input_tokens"], 512)

    def test_update_status_invalid_raises(self):
        client, _ = _mock_client()
        repo = MeetingJobRepository(client)
        with self.assertRaises(ValueError):
            repo.update_status("job-1", "nonexistent")

    def test_update_status_authorization_failed_allowed(self):
        row = self._make_row(status="authorization_failed")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.update_status("job-1", "authorization_failed", error_message="forbidden")
        self.assertEqual(result["status"], "authorization_failed")

    def test_update_status_scheduled_bot_capture_allowed(self):
        row = self._make_row(status="scheduled_bot_capture")
        client, chain = _mock_client(row)
        repo = MeetingJobRepository(client)
        result = repo.update_status("job-1", "scheduled_bot_capture")
        self.assertEqual(result["status"], "scheduled_bot_capture")

    def test_get_returns_row(self):
        row = self._make_row()
        client, chain = _mock_client(row)
        chain.execute.return_value = _ok(row)
        repo = MeetingJobRepository(client)
        result = repo.get("job-1")
        self.assertEqual(result["id"], "job-1")

    def test_list_by_tenant_returns_list(self):
        rows = [self._make_row(), self._make_row(id="job-2")]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingJobRepository(client)
        result = repo.list_by_tenant("t1")
        self.assertEqual(len(result), 2)

    def test_list_by_tenant_with_status_filter(self):
        rows = [self._make_row()]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingJobRepository(client)
        result = repo.list_by_tenant("t1", status="pending")
        self.assertEqual(len(result), 1)
        # Ensure .eq was called for the status filter
        calls = [str(c) for c in chain.eq.call_args_list]
        self.assertTrue(any("pending" in c for c in calls))

    def test_list_by_tenant_invalid_status_raises(self):
        client, _ = _mock_client()
        repo = MeetingJobRepository(client)
        with self.assertRaises(ValueError):
            repo.list_by_tenant("t1", status="garbage")


# ---------------------------------------------------------------------------
# MeetingArtifactRepository
# ---------------------------------------------------------------------------


class TestMeetingArtifactRepository(unittest.TestCase):

    def test_create_returns_row(self):
        row = {"id": "art-1", "meeting_job_id": "job-1", "artifact_type": "transcript", "storage_path": "/p"}
        client, chain = _mock_client(row)
        repo = MeetingArtifactRepository(client)
        result = repo.create(MeetingArtifact(meeting_job_id="job-1", artifact_type="transcript", storage_path="/p"))
        self.assertEqual(result["id"], "art-1")

    def test_create_includes_checksum_and_size(self):
        row = {"id": "art-1", "checksum": "abc123", "size_bytes": 512}
        client, chain = _mock_client(row)
        repo = MeetingArtifactRepository(client)
        repo.create(
            MeetingArtifact(
                meeting_job_id="job-1",
                artifact_type="captions_srt",
                storage_path="/p",
                checksum="abc123",
                size_bytes=512,
            )
        )
        inserted = chain.insert.call_args[0][0]
        self.assertEqual(inserted["checksum"], "abc123")
        self.assertEqual(inserted["size_bytes"], 512)

    def test_list_by_job(self):
        rows = [{"id": "art-1"}, {"id": "art-2"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingArtifactRepository(client)
        result = repo.list_by_job("job-1")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# GeneratedNotesRepository
# ---------------------------------------------------------------------------


class TestGeneratedNotesRepository(unittest.TestCase):

    def test_create_returns_row(self):
        row = {"id": "notes-1", "meeting_job_id": "job-1", "content": "Summary here."}
        client, chain = _mock_client(row)
        repo = GeneratedNotesRepository(client)
        result = repo.create(GeneratedNotes(meeting_job_id="job-1", content="Summary here."))
        self.assertEqual(result["id"], "notes-1")

    def test_update_content(self):
        row = {"id": "notes-1", "content": "Updated summary."}
        client, chain = _mock_client(row)
        repo = GeneratedNotesRepository(client)
        repo.update_content("notes-1", "Updated summary.", prompt_tokens=100, completion_tokens=50)
        patch_arg = chain.update.call_args[0][0]
        self.assertEqual(patch_arg["content"], "Updated summary.")
        self.assertEqual(patch_arg["prompt_tokens"], 100)
        self.assertEqual(patch_arg["completion_tokens"], 50)

    def test_update_content_only_content(self):
        row = {"id": "notes-1", "content": "New."}
        client, chain = _mock_client(row)
        repo = GeneratedNotesRepository(client)
        repo.update_content("notes-1", "New.")
        patch_arg = chain.update.call_args[0][0]
        self.assertNotIn("prompt_tokens", patch_arg)
        self.assertNotIn("completion_tokens", patch_arg)

    def test_list_by_job(self):
        rows = [{"id": "notes-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = GeneratedNotesRepository(client)
        result = repo.list_by_job("job-1")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# SharePointUploadRepository
# ---------------------------------------------------------------------------


class TestSharePointUploadRepository(unittest.TestCase):

    def test_create_returns_row(self):
        row = {
            "id": "sp-1",
            "meeting_job_id": "job-1",
            "sharepoint_item_id": "item-abc",
            "web_url": "https://contoso.sharepoint.com/...",
        }
        client, chain = _mock_client(row)
        repo = SharePointUploadRepository(client)
        result = repo.create(
            SharePointUpload(
                meeting_job_id="job-1",
                sharepoint_item_id="item-abc",
                web_url="https://contoso.sharepoint.com/...",
                drive_id="drv-1",
                site_id="site-1",
            )
        )
        self.assertEqual(result["sharepoint_item_id"], "item-abc")

    def test_create_stores_drive_and_site_ids(self):
        row = {"id": "sp-1"}
        client, chain = _mock_client(row)
        repo = SharePointUploadRepository(client)
        repo.create(
            SharePointUpload(
                meeting_job_id="job-1",
                sharepoint_item_id="item-abc",
                drive_id="drv-99",
                site_id="site-99",
            )
        )
        inserted = chain.insert.call_args[0][0]
        self.assertEqual(inserted["drive_id"], "drv-99")
        self.assertEqual(inserted["site_id"], "site-99")

    def test_list_by_job(self):
        rows = [{"id": "sp-1"}, {"id": "sp-2"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = SharePointUploadRepository(client)
        result = repo.list_by_job("job-1")
        self.assertEqual(len(result), 2)

    def test_create_allows_failed_upload_without_item_id(self):
        row = {"id": "sp-failed", "upload_status": "failed"}
        client, chain = _mock_client(row)
        repo = SharePointUploadRepository(client)
        repo.create(
            SharePointUpload(
                meeting_job_id="job-1",
                sharepoint_item_id=None,
                upload_status="failed",
                error_message="graph timeout",
                content_hash="abc123",
            )
        )
        inserted = chain.insert.call_args[0][0]
        self.assertIsNone(inserted.get("sharepoint_item_id"))
        self.assertEqual(inserted["upload_status"], "failed")
        self.assertEqual(inserted["error_message"], "graph timeout")
        self.assertEqual(inserted["content_hash"], "abc123")


# ---------------------------------------------------------------------------
# AuditEventRepository
# ---------------------------------------------------------------------------


class TestAuditEventRepository(unittest.TestCase):

    def test_append_inserts_event(self):
        row = {
            "id": "evt-1",
            "event_type": "meeting_job.created",
            "tenant_id": "t1",
            "resource_type": "meeting_job",
            "resource_id": "job-1",
        }
        client, chain = _mock_client(row)
        repo = AuditEventRepository(client)
        result = repo.append(
            AuditEvent(
                event_type="meeting_job.created",
                tenant_id="t1",
                resource_type="meeting_job",
                resource_id="job-1",
            )
        )
        self.assertEqual(result["event_type"], "meeting_job.created")
        chain.insert.assert_called_once()

    def test_append_only_no_update_method(self):
        """AuditEventRepository must not expose an update() method."""
        repo = AuditEventRepository(MagicMock())
        self.assertFalse(hasattr(repo, "update"), "AuditEventRepository must not expose update()")

    def test_append_only_no_delete_method(self):
        """AuditEventRepository must not expose a delete() method."""
        repo = AuditEventRepository(MagicMock())
        self.assertFalse(hasattr(repo, "delete"), "AuditEventRepository must not expose delete()")

    def test_list_by_resource(self):
        rows = [{"id": "evt-1"}, {"id": "evt-2"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = AuditEventRepository(client)
        result = repo.list_by_resource("meeting_job", "job-1")
        self.assertEqual(len(result), 2)

    def test_list_by_tenant(self):
        rows = [{"id": "evt-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = AuditEventRepository(client)
        result = repo.list_by_tenant("t1")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------


class TestClientModule(unittest.TestCase):

    def setUp(self):
        # Ensure cached client is cleared before each test
        from services.db import client as client_module

        client_module._reset_client()

    def test_get_client_raises_without_url(self):
        from services.db import client as client_module

        def fake_create(url, key):  # pragma: no cover
            return object()

        with patch.object(client_module, "create_client", fake_create):
            with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_KEY": "key"}, clear=False):
                with self.assertRaises(RuntimeError) as ctx:
                    client_module.get_client()
        self.assertIn("SUPABASE_URL", str(ctx.exception))

    def test_get_client_raises_without_key(self):
        from services.db import client as client_module

        def fake_create(url, key):  # pragma: no cover
            return object()

        with patch.object(client_module, "create_client", fake_create):
            with patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": ""}, clear=False):
                with self.assertRaises(RuntimeError) as ctx:
                    client_module.get_client()
        self.assertIn("SUPABASE_KEY", str(ctx.exception))

    def test_get_client_caches_instance(self):
        from services.db import client as client_module

        fake_supabase_client = object()

        def fake_create(url, key):
            return fake_supabase_client

        with patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "key"}):
            with patch.object(client_module, "create_client", fake_create):
                c1 = client_module.get_client()
                c2 = client_module.get_client()

        self.assertIs(c1, c2)
        self.assertIs(c1, fake_supabase_client)


# ---------------------------------------------------------------------------
# Model dataclass tests
# ---------------------------------------------------------------------------


class TestModels(unittest.TestCase):

    def test_meeting_job_defaults(self):
        job = MeetingJob(tenant_id="t1")
        self.assertEqual(job.source_type, "teams_native")
        self.assertEqual(job.status, "pending")
        self.assertIsNone(job.meeting_id)
        self.assertIsNone(job.model_name)

    def test_audit_event_metadata_default(self):
        evt = AuditEvent(event_type="test.event")
        self.assertEqual(evt.metadata, {})

    def test_tenant_settings_settings_default(self):
        ts = TenantSettings(tenant_id="t1")
        self.assertEqual(ts.settings, {})

    def test_meeting_artifact_asdict_excludes_nones_after_strip(self):
        artifact = MeetingArtifact(
            meeting_job_id="job-1",
            artifact_type="transcript",
            storage_path="/out/transcript.txt",
        )
        stripped = {k: v for k, v in asdict(artifact).items() if v is not None}
        self.assertNotIn("checksum", stripped)
        self.assertNotIn("size_bytes", stripped)

    def test_user_identity_fields(self):
        u = UserIdentity(tenant_id="t1", user_oid="oid-1", email="u@example.com", display_name="Alice")
        self.assertEqual(u.email, "u@example.com")
        self.assertEqual(u.display_name, "Alice")

    def test_sharepoint_upload_optional_fields(self):
        upload = SharePointUpload(meeting_job_id="job-1")
        self.assertIsNone(upload.sharepoint_item_id)
        self.assertIsNone(upload.web_url)
        self.assertIsNone(upload.drive_id)
        self.assertIsNone(upload.site_id)
        self.assertIsNone(upload.content_hash)
        self.assertEqual(upload.upload_status, "pending")
        self.assertIsNone(upload.error_message)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# UserProfileRepository
# ---------------------------------------------------------------------------


class TestUserProfileRepository(unittest.TestCase):

    def test_upsert_returns_row(self):
        row = {"id": "user-uuid-1", "email": "alice@example.com", "display_name": "Alice"}
        client, chain = _mock_client(row)
        repo = UserProfileRepository(client)
        result = repo.upsert(UserProfile(id="user-uuid-1", email="alice@example.com", display_name="Alice"))
        self.assertEqual(result["id"], "user-uuid-1")
        chain.upsert.assert_called_once()

    def test_upsert_uses_id_conflict_target(self):
        row = {"id": "user-uuid-1"}
        client, chain = _mock_client(row)
        repo = UserProfileRepository(client)
        repo.upsert(UserProfile(id="user-uuid-1"))
        _, kwargs = chain.upsert.call_args
        self.assertEqual(kwargs.get("on_conflict"), "id")

    def test_get_returns_row(self):
        row = {"id": "user-uuid-1", "email": "alice@example.com"}
        client, chain = _mock_client(row)
        chain.execute.return_value = _ok(row)
        repo = UserProfileRepository(client)
        result = repo.get("user-uuid-1")
        self.assertEqual(result["id"], "user-uuid-1")

    def test_upsert_strips_nones(self):
        row = {"id": "user-uuid-1"}
        client, chain = _mock_client(row)
        repo = UserProfileRepository(client)
        repo.upsert(UserProfile(id="user-uuid-1"))
        payload = chain.upsert.call_args[0][0]
        self.assertNotIn("email", payload)
        self.assertNotIn("display_name", payload)


# ---------------------------------------------------------------------------
# MicrosoftConnectionRepository
# ---------------------------------------------------------------------------


class TestMicrosoftConnectionRepository(unittest.TestCase):

    def _make_connection(self, **overrides):
        base = {
            "id": "conn-1",
            "owner_user_id": "user-uuid-1",
            "microsoft_user_oid": "ms-oid-1",
            "email": "alice@contoso.com",
        }
        base.update(overrides)
        return base

    def test_upsert_returns_row(self):
        row = self._make_connection()
        client, chain = _mock_client(row)
        repo = MicrosoftConnectionRepository(client)
        result = repo.upsert(MicrosoftConnection(owner_user_id="user-uuid-1", microsoft_user_oid="ms-oid-1"))
        self.assertEqual(result["owner_user_id"], "user-uuid-1")
        chain.upsert.assert_called_once()

    def test_upsert_conflict_target(self):
        row = self._make_connection()
        client, chain = _mock_client(row)
        repo = MicrosoftConnectionRepository(client)
        repo.upsert(MicrosoftConnection(owner_user_id="user-uuid-1", microsoft_user_oid="ms-oid-1"))
        _, kwargs = chain.upsert.call_args
        self.assertEqual(kwargs.get("on_conflict"), "owner_user_id,microsoft_user_oid")

    def test_get_returns_row(self):
        row = self._make_connection()
        client, chain = _mock_client(row)
        chain.execute.return_value = _ok(row)
        repo = MicrosoftConnectionRepository(client)
        result = repo.get("conn-1")
        self.assertEqual(result["id"], "conn-1")

    def test_get_by_user_and_oid(self):
        row = self._make_connection()
        client, chain = _mock_client(row)
        chain.execute.return_value = _ok(row)
        repo = MicrosoftConnectionRepository(client)
        result = repo.get_by_user_and_oid("user-uuid-1", "ms-oid-1")
        self.assertEqual(result["microsoft_user_oid"], "ms-oid-1")
        calls = [str(c) for c in chain.eq.call_args_list]
        self.assertTrue(any("ms-oid-1" in c for c in calls))

    def test_list_by_user(self):
        rows = [self._make_connection(), self._make_connection(id="conn-2")]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MicrosoftConnectionRepository(client)
        result = repo.list_by_user("user-uuid-1")
        self.assertEqual(len(result), 2)

    def test_delete_calls_delete(self):
        client, chain = _mock_client()
        repo = MicrosoftConnectionRepository(client)
        repo.delete("conn-1")
        chain.delete.assert_called_once()


# ---------------------------------------------------------------------------
# list_by_user tests for user-scoped repositories
# ---------------------------------------------------------------------------


class TestMeetingJobRepositoryListByUser(unittest.TestCase):

    def test_list_by_user_returns_rows(self):
        rows = [{"id": "job-1", "owner_user_id": "user-1"}, {"id": "job-2", "owner_user_id": "user-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingJobRepository(client)
        result = repo.list_by_user("user-1")
        self.assertEqual(len(result), 2)

    def test_list_by_user_with_status_filter(self):
        rows = [{"id": "job-1", "owner_user_id": "user-1", "status": "completed"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingJobRepository(client)
        result = repo.list_by_user("user-1", status="completed")
        self.assertEqual(len(result), 1)
        calls = [str(c) for c in chain.eq.call_args_list]
        self.assertTrue(any("completed" in c for c in calls))

    def test_list_by_user_invalid_status_raises(self):
        client, _ = _mock_client()
        repo = MeetingJobRepository(client)
        with self.assertRaises(ValueError):
            repo.list_by_user("user-1", status="not_a_status")


class TestMeetingArtifactRepositoryListByUser(unittest.TestCase):

    def test_list_by_user_returns_rows(self):
        rows = [{"id": "art-1", "owner_user_id": "user-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = MeetingArtifactRepository(client)
        result = repo.list_by_user("user-1")
        self.assertEqual(len(result), 1)


class TestGeneratedNotesRepositoryListByUser(unittest.TestCase):

    def test_list_by_user_returns_rows(self):
        rows = [{"id": "notes-1", "owner_user_id": "user-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = GeneratedNotesRepository(client)
        result = repo.list_by_user("user-1")
        self.assertEqual(len(result), 1)


class TestSharePointUploadRepositoryListByUser(unittest.TestCase):

    def test_list_by_user_returns_rows(self):
        rows = [{"id": "sp-1", "owner_user_id": "user-1"}, {"id": "sp-2", "owner_user_id": "user-1"}]
        client, chain = _mock_client()
        chain.execute.return_value = _ok(rows)
        repo = SharePointUploadRepository(client)
        result = repo.list_by_user("user-1")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Model dataclass tests – owner_user_id / new fields
# ---------------------------------------------------------------------------


class TestOwnerUserIdModels(unittest.TestCase):

    def test_meeting_job_owner_user_id_defaults_none(self):
        job = MeetingJob(tenant_id="t1")
        self.assertIsNone(job.owner_user_id)

    def test_meeting_job_accepts_owner_user_id(self):
        job = MeetingJob(tenant_id="t1", owner_user_id="user-uuid-1")
        self.assertEqual(job.owner_user_id, "user-uuid-1")

    def test_meeting_artifact_owner_user_id_defaults_none(self):
        art = MeetingArtifact(meeting_job_id="job-1", artifact_type="transcript", storage_path="/p")
        self.assertIsNone(art.owner_user_id)

    def test_generated_notes_owner_user_id_defaults_none(self):
        notes = GeneratedNotes(meeting_job_id="job-1")
        self.assertIsNone(notes.owner_user_id)

    def test_sharepoint_upload_owner_user_id_defaults_none(self):
        upload = SharePointUpload(meeting_job_id="job-1")
        self.assertIsNone(upload.owner_user_id)

    def test_user_profile_fields(self):
        p = UserProfile(id="user-uuid-1", email="a@b.com", display_name="Alice")
        self.assertEqual(p.id, "user-uuid-1")
        self.assertEqual(p.email, "a@b.com")
        self.assertEqual(p.display_name, "Alice")
        self.assertIsNone(p.created_at)

    def test_microsoft_connection_fields(self):
        conn = MicrosoftConnection(owner_user_id="user-1", microsoft_user_oid="ms-oid-1")
        self.assertEqual(conn.owner_user_id, "user-1")
        self.assertEqual(conn.microsoft_user_oid, "ms-oid-1")
        self.assertIsNone(conn.access_token)
        self.assertIsNone(conn.refresh_token)
        self.assertIsNone(conn.scopes)
