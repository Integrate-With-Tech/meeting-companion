"""
Tests for services.notes_storage.
"""

from dataclasses import asdict
from datetime import date
import unittest

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notes_storage import (  # noqa: E402
    NotesUploadResult,
    build_generated_note_exports,
    persist_generated_notes,
    resolve_sharepoint_destination,
)


class _MemoryRepo:
    def __init__(self, with_ids: bool = True):
        self.rows = []
        self._with_ids = with_ids

    def create(self, row):
        payload = asdict(row)
        if self._with_ids and not payload.get("id"):
            payload["id"] = f"row-{len(self.rows)+1}"
        self.rows.append(payload)
        return payload


class _AuditRepo:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(asdict(event))
        return self.events[-1]


class _SuccessAdapter:
    def upload_text(self, *, destination, filename, text_content, content_type):
        return NotesUploadResult(
            item_id=f"item-{filename}",
            web_url=f"https://contoso.sharepoint.com/{filename}",
            content_hash=f"hash-{filename}",
            uploaded_at="2026-06-06T10:00:00+00:00",
        )


class _FailAdapter:
    def upload_text(self, *, destination, filename, text_content, content_type):
        raise RuntimeError(f"upload failed for {filename}")


class TestBuildGeneratedNoteExports(unittest.TestCase):
    def test_builds_required_filenames_and_formats(self):
        files = build_generated_note_exports(
            meeting_date=date(2026, 6, 6),
            meeting_title="Q2 Product Review",
            markdown_notes="# Notes\n- Update\n",
            structured_notes={"title": "Q2 Product Review", "actions": ["Ship"]},
        )
        self.assertEqual(files["markdown"].filename, "2026-06-06-q2-product-review-notes.md")
        self.assertEqual(files["json"].filename, "2026-06-06-q2-product-review-notes.json")
        self.assertTrue(files["json"].text_content.endswith("\n"))


class TestResolveSharePointDestination(unittest.TestCase):
    def test_resolves_nested_sharepoint_settings(self):
        destination = resolve_sharepoint_destination(
            {"sharepoint": {"site_id": "site-1", "drive_id": "drive-1", "folder_path": "Meetings/2026"}}
        )
        self.assertIsNotNone(destination)
        self.assertEqual(destination.site_id, "site-1")
        self.assertEqual(destination.drive_id, "drive-1")
        self.assertEqual(destination.folder_path, "Meetings/2026")

    def test_returns_none_when_missing_required_ids(self):
        self.assertIsNone(resolve_sharepoint_destination({"sharepoint": {"site_id": "site-1"}}))


class TestPersistGeneratedNotes(unittest.TestCase):
    def test_persists_notes_artifacts_and_uploads(self):
        notes_repo = _MemoryRepo()
        artifacts_repo = _MemoryRepo()
        uploads_repo = _MemoryRepo()
        audit_repo = _AuditRepo()

        result = persist_generated_notes(
            meeting_job_id="job-1",
            meeting_date=date(2026, 6, 6),
            meeting_title="Sprint Planning",
            markdown_notes="# Meeting Notes\n- Item 1\n",
            structured_notes={"summary": "Item 1", "actions": ["Do thing"]},
            tenant_settings={"sharepoint": {"site_id": "site-1", "drive_id": "drive-1", "folder_path": "Notes"}},
            generated_notes_repo=notes_repo,
            artifacts_repo=artifacts_repo,
            sharepoint_uploads_repo=uploads_repo,
            storage_adapter=_SuccessAdapter(),
            audit_repo=audit_repo,
            tenant_id="tenant-1",
            owner_user_id="user-1",
            actor_email="user-1@example.com",
        )

        self.assertEqual(len(notes_repo.rows), 1)
        self.assertEqual(len(artifacts_repo.rows), 2)
        self.assertEqual(len(uploads_repo.rows), 2)
        self.assertEqual([u["upload_status"] for u in uploads_repo.rows], ["uploaded", "uploaded"])
        self.assertEqual(len(result["downloads"]), 2)
        self.assertTrue(any(d["filename"].endswith(".md") for d in result["downloads"]))
        self.assertTrue(any(d["filename"].endswith(".json") for d in result["downloads"]))
        self.assertEqual(
            [evt["event_type"] for evt in audit_repo.events],
            ["notes.generated", "sharepoint.upload_succeeded", "sharepoint.upload_succeeded"],
        )

    def test_keeps_local_exports_when_sharepoint_upload_fails(self):
        notes_repo = _MemoryRepo()
        artifacts_repo = _MemoryRepo()
        uploads_repo = _MemoryRepo()
        audit_repo = _AuditRepo()

        result = persist_generated_notes(
            meeting_job_id="job-2",
            meeting_date=date(2026, 6, 7),
            meeting_title="Ops Review",
            markdown_notes="# Ops\n- Risk update\n",
            structured_notes={"summary": "Risk update"},
            tenant_settings={"sharepoint_site_id": "site-flat", "sharepoint_drive_id": "drive-flat"},
            generated_notes_repo=notes_repo,
            artifacts_repo=artifacts_repo,
            sharepoint_uploads_repo=uploads_repo,
            storage_adapter=_FailAdapter(),
            audit_repo=audit_repo,
        )

        self.assertEqual(len(result["downloads"]), 2)
        self.assertEqual(len(uploads_repo.rows), 2)
        self.assertEqual([u["upload_status"] for u in uploads_repo.rows], ["failed", "failed"])
        for row in uploads_repo.rows:
            self.assertIn("upload failed for", row["error_message"])
            self.assertIsNone(row["sharepoint_item_id"])
        self.assertEqual(
            [evt["event_type"] for evt in audit_repo.events],
            ["notes.generated", "sharepoint.upload_failed", "sharepoint.upload_failed"],
        )


if __name__ == "__main__":
    unittest.main()
