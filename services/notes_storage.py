"""
Meeting-note persistence and export helpers.

Builds markdown/json notes files, persists metadata, and uploads to SharePoint
through an adapter boundary so additional providers (e.g. Google Drive) can be
implemented behind the same interface later.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from services.db.models import AuditEvent, GeneratedNotes, MeetingArtifact, SharePointUpload


@dataclass
class SharePointDestination:
    site_id: str
    drive_id: str
    folder_path: str = ""


@dataclass
class NotesUploadResult:
    item_id: str
    web_url: Optional[str] = None
    content_hash: Optional[str] = None
    uploaded_at: Optional[str] = None


@dataclass
class LocalExportFile:
    filename: str
    content_type: str
    text_content: str
    content_hash: str


class NotesStorageAdapter(Protocol):
    """Abstract storage adapter for note-file uploads."""

    def upload_text(
        self,
        *,
        destination: SharePointDestination,
        filename: str,
        text_content: str,
        content_type: str,
    ) -> NotesUploadResult:
        """Upload text content and return provider metadata."""


class SharePointGraphAdapter:
    """
    Microsoft Graph-backed SharePoint adapter.

    Expects ``graph_client`` to provide::

        upload_drive_item(
            site_id=...,
            drive_id=...,
            folder_path=...,
            filename=...,
            content_bytes=...,
            content_type=...,
        ) -> dict
    """

    def __init__(self, graph_client: Any) -> None:
        self._graph_client = graph_client

    def upload_text(
        self,
        *,
        destination: SharePointDestination,
        filename: str,
        text_content: str,
        content_type: str,
    ) -> NotesUploadResult:
        payload = text_content.encode("utf-8")
        response = self._graph_client.upload_drive_item(
            site_id=destination.site_id,
            drive_id=destination.drive_id,
            folder_path=destination.folder_path,
            filename=filename,
            content_bytes=payload,
            content_type=content_type,
        )
        item_id = str(response.get("id", "")).strip()
        if not item_id:
            raise RuntimeError("Graph upload did not return an item ID.")
        return NotesUploadResult(
            item_id=item_id,
            web_url=response.get("webUrl"),
            content_hash=_extract_graph_content_hash(response) or hashlib.sha256(payload).hexdigest(),
            uploaded_at=response.get("lastModifiedDateTime") or _utc_now_iso(),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "meeting"


def _extract_graph_content_hash(response: Dict[str, Any]) -> Optional[str]:
    file_obj = response.get("file")
    if isinstance(file_obj, dict):
        hashes = file_obj.get("hashes")
        if isinstance(hashes, dict):
            for key in ("sha256Hash", "quickXorHash"):
                value = hashes.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    e_tag = response.get("eTag")
    if isinstance(e_tag, str) and e_tag.strip():
        return e_tag.strip()
    return None


def resolve_sharepoint_destination(settings: Dict[str, Any]) -> Optional[SharePointDestination]:
    """Resolve destination from tenant settings, supporting nested or flat keys."""
    sharepoint_settings = settings.get("sharepoint", {})
    if not isinstance(sharepoint_settings, dict):
        sharepoint_settings = {}

    site_id = sharepoint_settings.get("site_id") or settings.get("sharepoint_site_id")
    drive_id = sharepoint_settings.get("drive_id") or settings.get("sharepoint_drive_id")
    folder_path = (
        sharepoint_settings.get("folder_path")
        or sharepoint_settings.get("folder")
        or settings.get("sharepoint_folder_path")
        or ""
    )
    if not isinstance(site_id, str) or not site_id.strip():
        return None
    if not isinstance(drive_id, str) or not drive_id.strip():
        return None
    folder_value = folder_path if isinstance(folder_path, str) else ""
    return SharePointDestination(site_id=site_id.strip(), drive_id=drive_id.strip(), folder_path=folder_value.strip())


def build_generated_note_exports(
    *,
    meeting_date: date,
    meeting_title: str,
    markdown_notes: str,
    structured_notes: Dict[str, Any],
) -> Dict[str, LocalExportFile]:
    """Create markdown/json note files using the required naming convention."""
    stem = f"{meeting_date.isoformat()}-{_slugify(meeting_title)}-notes"
    markdown_bytes = markdown_notes.encode("utf-8")
    json_text = json.dumps(structured_notes, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_bytes = json_text.encode("utf-8")
    return {
        "markdown": LocalExportFile(
            filename=f"{stem}.md",
            content_type="text/markdown; charset=utf-8",
            text_content=markdown_notes,
            content_hash=hashlib.sha256(markdown_bytes).hexdigest(),
        ),
        "json": LocalExportFile(
            filename=f"{stem}.json",
            content_type="application/json; charset=utf-8",
            text_content=json_text,
            content_hash=hashlib.sha256(json_bytes).hexdigest(),
        ),
    }


def persist_generated_notes(
    *,
    meeting_job_id: str,
    meeting_date: date,
    meeting_title: str,
    markdown_notes: str,
    structured_notes: Dict[str, Any],
    tenant_settings: Dict[str, Any],
    generated_notes_repo: Any,
    artifacts_repo: Any,
    sharepoint_uploads_repo: Any,
    storage_adapter: Optional[NotesStorageAdapter] = None,
    audit_repo: Optional[Any] = None,
    tenant_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persist generated notes/artifacts and attempt SharePoint uploads.

    Local export payloads are always returned even when SharePoint upload fails.
    """
    exports = build_generated_note_exports(
        meeting_date=meeting_date,
        meeting_title=meeting_title,
        markdown_notes=markdown_notes,
        structured_notes=structured_notes,
    )

    notes_row = generated_notes_repo.create(GeneratedNotes(meeting_job_id=meeting_job_id, content=markdown_notes))
    if audit_repo is not None:
        audit_repo.append(
            AuditEvent(
                event_type="notes.generated",
                actor_id=owner_user_id,
                actor_email=actor_email,
                tenant_id=tenant_id,
                resource_type="generated_notes",
                resource_id=str(notes_row.get("id", "")) or None,
                metadata={"meeting_job_id": meeting_job_id},
            )
        )

    artifact_rows: List[Dict[str, Any]] = []
    artifact_by_key: Dict[str, Dict[str, Any]] = {}
    for key, artifact_type in (("markdown", "notes_markdown"), ("json", "notes_json")):
        export_file = exports[key]
        artifact_row = artifacts_repo.create(
            MeetingArtifact(
                meeting_job_id=meeting_job_id,
                artifact_type=artifact_type,
                storage_path=export_file.filename,
                checksum=export_file.content_hash,
                size_bytes=len(export_file.text_content.encode("utf-8")),
            )
        )
        artifact_rows.append(artifact_row)
        artifact_by_key[key] = artifact_row

    upload_rows: List[Dict[str, Any]] = []
    destination = resolve_sharepoint_destination(tenant_settings)
    if destination and storage_adapter:
        for key in ("markdown", "json"):
            export_file = exports[key]
            artifact_row = artifact_by_key[key]
            try:
                upload_result = storage_adapter.upload_text(
                    destination=destination,
                    filename=export_file.filename,
                    text_content=export_file.text_content,
                    content_type=export_file.content_type,
                )
                upload_row = sharepoint_uploads_repo.create(
                    SharePointUpload(
                        meeting_job_id=meeting_job_id,
                        artifact_id=artifact_row.get("id"),
                        sharepoint_item_id=upload_result.item_id,
                        web_url=upload_result.web_url,
                        drive_id=destination.drive_id,
                        site_id=destination.site_id,
                        content_hash=upload_result.content_hash or export_file.content_hash,
                        upload_status="uploaded",
                        uploaded_at=upload_result.uploaded_at or _utc_now_iso(),
                    )
                )
                if audit_repo is not None:
                    audit_repo.append(
                        AuditEvent(
                            event_type="sharepoint.upload_succeeded",
                            actor_id=owner_user_id,
                            actor_email=actor_email,
                            tenant_id=tenant_id,
                            resource_type="sharepoint_upload",
                            resource_id=str(upload_row.get("id", "")) or None,
                            metadata={
                                "meeting_job_id": meeting_job_id,
                                "artifact_id": artifact_row.get("id"),
                                "filename": export_file.filename,
                            },
                        )
                    )
            except Exception as exc:  # pragma: no cover - validated via tests
                upload_row = sharepoint_uploads_repo.create(
                    SharePointUpload(
                        meeting_job_id=meeting_job_id,
                        artifact_id=artifact_row.get("id"),
                        drive_id=destination.drive_id,
                        site_id=destination.site_id,
                        content_hash=export_file.content_hash,
                        upload_status="failed",
                        error_message=str(exc),
                        uploaded_at=_utc_now_iso(),
                    )
                )
                if audit_repo is not None:
                    audit_repo.append(
                        AuditEvent(
                            event_type="sharepoint.upload_failed",
                            actor_id=owner_user_id,
                            actor_email=actor_email,
                            tenant_id=tenant_id,
                            resource_type="sharepoint_upload",
                            resource_id=str(upload_row.get("id", "")) or None,
                            metadata={
                                "meeting_job_id": meeting_job_id,
                                "artifact_id": artifact_row.get("id"),
                                "filename": export_file.filename,
                                "error": str(exc),
                            },
                        )
                    )
            upload_rows.append(upload_row)

    return {
        "notes": notes_row,
        "artifacts": artifact_rows,
        "uploads": upload_rows,
        "downloads": [
            {
                "filename": export_file.filename,
                "content_type": export_file.content_type,
                "content": export_file.text_content,
                "content_hash": export_file.content_hash,
            }
            for export_file in exports.values()
        ],
    }
