"""
FastAPI template-based UI for setup/readiness and meeting notes browsing.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from services.db import get_client
from services.db.models import TenantSettings
from services.db.models import AuditEvent, MicrosoftConnection, UserProfile
from services.db.repository import (
    AuditEventRepository,
    GeneratedNotesRepository,
    MeetingArtifactRepository,
    MeetingJobRepository,
    MicrosoftConnectionRepository,
    SharePointUploadRepository,
    TenantSettingsRepository,
    UserProfileRepository,
)

SUPPORTED_SOCIAL_PROVIDERS = frozenset({"google", "github"})


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "meeting"


def _parse_notes_sections(content: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current = "summary"
    sections.setdefault(current, [])
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = line.lstrip("#").strip().lower()
            sections.setdefault(current, [])
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        sections.setdefault(current, []).append(line)
    return sections


def _first_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return fallback


def _build_upload_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "pending"
    statuses = [str(row.get("upload_status", "pending")) for row in rows]
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status == "uploaded" for status in statuses):
        return "uploaded"
    return "pending"


class NotesUIService:
    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client or get_client()
        self._tenant_settings = TenantSettingsRepository(self._client)
        self._jobs = MeetingJobRepository(self._client)
        self._notes = GeneratedNotesRepository(self._client)
        self._artifacts = MeetingArtifactRepository(self._client)
        self._uploads = SharePointUploadRepository(self._client)
        self._audit = AuditEventRepository(self._client)
        self._profiles = UserProfileRepository(self._client)
        self._ms_connections = MicrosoftConnectionRepository(self._client)

    def _append_audit(self, event: AuditEvent) -> None:
        try:
            self._audit.append(event)
        except Exception:
            return

    def get_setup_settings(self, tenant_id: str) -> Dict[str, Any]:
        row = self._tenant_settings.get_by_tenant(tenant_id) or {}
        settings = row.get("settings") or {}
        graph = settings.get("graph") or {}
        sharepoint = settings.get("sharepoint") or {}
        openai = settings.get("openai") or {}
        supabase = settings.get("supabase") or {}
        webhook = settings.get("webhook") or {}
        return {
            "graph_client_id": graph.get("client_id", ""),
            "graph_tenant_id": graph.get("tenant_id", ""),
            "graph_client_secret": graph.get("client_secret", ""),
            "sharepoint_site_id": sharepoint.get("site_id", ""),
            "sharepoint_drive_id": sharepoint.get("drive_id", ""),
            "sharepoint_folder_path": sharepoint.get("folder_path", ""),
            "openai_api_key": openai.get("api_key", ""),
            "openai_model": openai.get("model", ""),
            "supabase_url": supabase.get("url", ""),
            "supabase_key": supabase.get("key", ""),
            "webhook_url": webhook.get("url", ""),
        }

    def save_setup_settings(self, tenant_id: str, form_values: Dict[str, str]) -> Dict[str, Any]:
        payload = {
            "graph": {
                "client_id": form_values.get("graph_client_id", ""),
                "tenant_id": form_values.get("graph_tenant_id", ""),
                "client_secret": form_values.get("graph_client_secret", ""),
            },
            "sharepoint": {
                "site_id": form_values.get("sharepoint_site_id", ""),
                "drive_id": form_values.get("sharepoint_drive_id", ""),
                "folder_path": form_values.get("sharepoint_folder_path", ""),
            },
            "openai": {
                "api_key": form_values.get("openai_api_key", ""),
                "model": form_values.get("openai_model", ""),
            },
            "supabase": {
                "url": form_values.get("supabase_url", ""),
                "key": form_values.get("supabase_key", ""),
            },
            "webhook": {"url": form_values.get("webhook_url", "")},
        }
        self._tenant_settings.upsert(TenantSettings(tenant_id=tenant_id, settings=payload))
        return self.get_setup_settings(tenant_id)

    def get_readiness_checks(self, tenant_id: str) -> List[Dict[str, Any]]:
        settings = self.get_setup_settings(tenant_id)
        supabase_ok = True
        try:
            self._tenant_settings.get_by_tenant(tenant_id)
        except Exception:
            supabase_ok = False
        checks = [
            {
                "key": "graph_permissions",
                "label": "Graph permissions",
                "ready": bool(settings["graph_client_id"] and settings["graph_tenant_id"] and settings["graph_client_secret"]),
            },
            {
                "key": "transcript_access",
                "label": "Transcript access",
                "ready": bool(self._jobs.list_by_tenant(tenant_id, limit=1)),
            },
            {
                "key": "sharepoint_folder_access",
                "label": "SharePoint folder access",
                "ready": bool(settings["sharepoint_site_id"] and settings["sharepoint_drive_id"]),
            },
            {"key": "openai_connectivity", "label": "OpenAI connectivity", "ready": bool(settings["openai_api_key"])},
            {"key": "supabase_connection", "label": "Supabase connection", "ready": supabase_ok},
            {"key": "webhook_status", "label": "Webhook status", "ready": bool(settings["webhook_url"])},
        ]
        return checks

    def list_notes(
        self,
        *,
        tenant_id: str,
        viewer_id: str,
        is_admin: bool,
        filters: Dict[str, str],
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not is_admin and viewer_id:
            jobs = self._jobs.list_by_user(viewer_id, limit=limit)
        else:
            jobs = self._jobs.list_by_tenant(tenant_id, limit=limit)
        job_ids = [str(job.get("id")) for job in jobs if job.get("id")]
        notes_by_job = self._group_rows_by_job_id("generated_notes", job_ids)
        uploads_by_job = self._group_rows_by_job_id("sharepoint_uploads", job_ids)
        for job in jobs:
            if not is_admin and viewer_id and str(job.get("owner_user_id", "")) != viewer_id:
                continue
            notes_rows = notes_by_job.get(str(job["id"]), [])
            notes_content = notes_rows[0]["content"] if notes_rows else ""
            uploads = uploads_by_job.get(str(job["id"]), [])
            created_at = str(job.get("created_at") or "")
            item = {
                "meeting_job_id": job["id"],
                "meeting_title": _first_title(notes_content, str(job.get("meeting_id") or job["id"])),
                "created_at": created_at,
                "date": created_at[:10],
                "organizer": str(job.get("created_by") or "unassigned"),
                "status": str(job.get("status") or "pending"),
                "transcript_source": str(job.get("source_type") or ""),
                "upload_status": _build_upload_status(uploads),
            }
            rows.append(item)
        filtered = []
        for row in rows:
            if filters.get("date") and row["date"] != filters["date"]:
                continue
            if filters.get("organizer") and filters["organizer"].lower() not in row["organizer"].lower():
                continue
            if filters.get("status") and row["status"] != filters["status"]:
                continue
            if filters.get("transcript_source") and row["transcript_source"] != filters["transcript_source"]:
                continue
            if filters.get("upload_status") and row["upload_status"] != filters["upload_status"]:
                continue
            filtered.append(row)
        self._append_audit(
            AuditEvent(
                event_type="user_access.notes_history_viewed",
                actor_id=viewer_id or None,
                tenant_id=tenant_id,
                resource_type="notes_history",
                metadata={"result_count": len(filtered), "is_admin": is_admin},
            )
        )
        return filtered

    def _group_rows_by_job_id(self, table_name: str, job_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not job_ids:
            return {}
        try:
            rows = self._client.table(table_name).select("*").in_("meeting_job_id", job_ids).execute().data
        except Exception:
            rows = []
            for meeting_job_id in job_ids:
                if table_name == "generated_notes":
                    rows.extend(self._notes.list_by_job(meeting_job_id))
                elif table_name == "sharepoint_uploads":
                    rows.extend(self._uploads.list_by_job(meeting_job_id))
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("meeting_job_id", ""))
            grouped.setdefault(key, []).append(row)
        return grouped

    def get_note_detail(
        self, *, tenant_id: str, meeting_job_id: str, viewer_id: str, is_admin: bool
    ) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(meeting_job_id)
        if not job or str(job.get("tenant_id")) != tenant_id:
            return None
        if not is_admin and viewer_id and str(job.get("owner_user_id", "")) != viewer_id:
            return None

        notes_rows = self._notes.list_by_job(meeting_job_id)
        notes = notes_rows[0] if notes_rows else {}
        content = str(notes.get("content") or "")
        sections = _parse_notes_sections(content)
        uploads = self._uploads.list_by_job(meeting_job_id)
        artifacts = self._artifacts.list_by_job(meeting_job_id)
        sharepoint_links = [str(row.get("web_url")) for row in uploads if row.get("web_url")]
        audit_events = self._audit.list_by_resource("meeting_job", meeting_job_id, limit=50)

        meeting_title = _first_title(content, str(job.get("meeting_id") or meeting_job_id))
        self._append_audit(
            AuditEvent(
                event_type="user_access.meeting_notes_viewed",
                actor_id=viewer_id or None,
                tenant_id=tenant_id,
                resource_type="meeting_job",
                resource_id=meeting_job_id,
                metadata={"is_admin": is_admin},
            )
        )
        return {
            "meeting_job_id": meeting_job_id,
            "meeting_title": meeting_title,
            "meeting_date": str(job.get("created_at") or "")[:10],
            "agenda": sections.get("agenda", []),
            "action_items": sections.get("action items", []),
            "decisions": sections.get("decisions", []),
            "sharepoint_links": sharepoint_links,
            "transcript_source": str(job.get("source_type") or ""),
            "status": str(job.get("status") or ""),
            "model_name": notes.get("model_name") or job.get("model_name") or "",
            "model_version": notes.get("model_version") or job.get("model_version") or "",
            "prompt_tokens": notes.get("prompt_tokens"),
            "completion_tokens": notes.get("completion_tokens"),
            "audit_status": "events_recorded" if audit_events else "no_events",
            "artifacts": artifacts,
            "content": content,
            "upload_status": _build_upload_status(uploads),
        }

    def build_download(self, detail: Dict[str, Any], fmt: str) -> Dict[str, str]:
        meeting_date = detail.get("meeting_date") or datetime.now(timezone.utc).date().isoformat()
        stem = f"{meeting_date}-{_slugify(str(detail.get('meeting_title') or 'meeting'))}-notes"
        if fmt == "markdown":
            export = {
                "filename": f"{stem}.md",
                "content": str(detail.get("content") or ""),
                "content_type": "text/markdown; charset=utf-8",
            }
            self._append_audit(
                AuditEvent(
                    event_type="user_access.notes_downloaded",
                    resource_type="meeting_job",
                    resource_id=str(detail.get("meeting_job_id") or ""),
                    metadata={"format": fmt},
                )
            )
            return export
        if fmt == "json":
            payload = {
                "meeting_job_id": detail["meeting_job_id"],
                "meeting_title": detail["meeting_title"],
                "agenda": detail["agenda"],
                "action_items": detail["action_items"],
                "decisions": detail["decisions"],
                "transcript_source": detail["transcript_source"],
                "status": detail["status"],
                "model_name": detail["model_name"],
                "model_version": detail["model_version"],
                "prompt_tokens": detail["prompt_tokens"],
                "completion_tokens": detail["completion_tokens"],
                "audit_status": detail["audit_status"],
                "sharepoint_links": detail["sharepoint_links"],
            }
            export = {
                "filename": f"{stem}.json",
                "content": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                "content_type": "application/json; charset=utf-8",
            }
            self._append_audit(
                AuditEvent(
                    event_type="user_access.notes_downloaded",
                    resource_type="meeting_job",
                    resource_id=str(detail.get("meeting_job_id") or ""),
                    metadata={"format": fmt},
                )
            )
            return export
        raise ValueError(f"Unsupported format {fmt!r}")

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Return the profile row for *user_id*, or ``None`` if not found."""
        if not user_id:
            return None
        return self._profiles.get(user_id)

    def list_microsoft_connections(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all Microsoft connection rows for *user_id*."""
        if not user_id:
            return []
        return self._ms_connections.list_by_user(user_id)

    def check_microsoft_connected(self, user_id: str) -> bool:
        """Return ``True`` if *user_id* has at least one Microsoft connection."""
        return bool(self.list_microsoft_connections(user_id))

    def disconnect_microsoft(self, user_id: str, connection_id: str) -> bool:
        """Delete the Microsoft connection identified by *connection_id*.

        Returns ``True`` if the row was owned by *user_id* and deleted, or
        ``False`` if the row was not found or belongs to a different user.
        """
        if not user_id or not connection_id:
            return False
        conn = self._ms_connections.get(connection_id)
        if not conn or str(conn.get("owner_user_id")) != user_id:
            return False
        self._ms_connections.delete(connection_id)
        self._append_audit(
            AuditEvent(
                event_type="microsoft_connection.disconnected",
                actor_id=user_id,
                resource_type="microsoft_connection",
                resource_id=connection_id,
            )
        )
        return True

    def upsert_user_profile(self, user_id: str, *, email: str = "", display_name: str = "") -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        profile = self._profiles.upsert(UserProfile(id=user_id, email=email or None, display_name=display_name or None))
        self._append_audit(
            AuditEvent(
                event_type="auth.sign_in",
                actor_id=user_id,
                actor_email=email or None,
                resource_type="profile",
                resource_id=user_id,
                metadata={"method": "social_or_callback"},
            )
        )
        return profile

    def connect_microsoft(
        self,
        user_id: str,
        *,
        microsoft_user_oid: str,
        email: str = "",
        display_name: str = "",
        tenant_id: str = "",
        access_token: str = "",
        refresh_token: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not user_id or not microsoft_user_oid:
            return None
        row = self._ms_connections.upsert(
            MicrosoftConnection(
                owner_user_id=user_id,
                microsoft_user_oid=microsoft_user_oid,
                email=email or None,
                display_name=display_name or None,
                tenant_id=tenant_id or None,
                access_token=access_token or None,
                refresh_token=refresh_token or None,
            )
        )
        self._append_audit(
            AuditEvent(
                event_type="microsoft_connection.connected",
                actor_id=user_id,
                actor_email=email or None,
                resource_type="microsoft_connection",
                resource_id=str(row.get("id", "")) or None,
                metadata={"microsoft_user_oid": microsoft_user_oid},
            )
        )
        return row


def create_app(data_service: Optional[Any] = None) -> FastAPI:
    app = FastAPI(title="Meeting Companion Notes UI")
    service: Dict[str, Any] = {"value": data_service}
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

    def _service() -> Any:
        if service["value"] is None:
            service["value"] = NotesUIService()
        return service["value"]

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="home.html")

    @app.get("/admin/setup", response_class=HTMLResponse)
    def admin_setup(request: Request, tenant_id: str = Query("default")) -> HTMLResponse:
        settings = _service().get_setup_settings(tenant_id)
        return templates.TemplateResponse(
            request=request,
            name="admin_setup.html",
            context={"tenant_id": tenant_id, "settings": settings, "saved": False},
        )

    @app.post("/admin/setup", response_class=HTMLResponse)
    def save_admin_setup(
        request: Request,
        tenant_id: str = Form(...),
        graph_client_id: str = Form(""),
        graph_tenant_id: str = Form(""),
        graph_client_secret: str = Form(""),
        sharepoint_site_id: str = Form(""),
        sharepoint_drive_id: str = Form(""),
        sharepoint_folder_path: str = Form(""),
        openai_api_key: str = Form(""),
        openai_model: str = Form(""),
        supabase_url: str = Form(""),
        supabase_key: str = Form(""),
        webhook_url: str = Form(""),
    ) -> HTMLResponse:
        settings = _service().save_setup_settings(
            tenant_id,
            {
                "graph_client_id": graph_client_id,
                "graph_tenant_id": graph_tenant_id,
                "graph_client_secret": graph_client_secret,
                "sharepoint_site_id": sharepoint_site_id,
                "sharepoint_drive_id": sharepoint_drive_id,
                "sharepoint_folder_path": sharepoint_folder_path,
                "openai_api_key": openai_api_key,
                "openai_model": openai_model,
                "supabase_url": supabase_url,
                "supabase_key": supabase_key,
                "webhook_url": webhook_url,
            },
        )
        return templates.TemplateResponse(
            request=request,
            name="admin_setup.html",
            context={"tenant_id": tenant_id, "settings": settings, "saved": True},
        )

    @app.get("/admin/readiness", response_class=HTMLResponse)
    def readiness(request: Request, tenant_id: str = Query("default")) -> HTMLResponse:
        checks = _service().get_readiness_checks(tenant_id)
        return templates.TemplateResponse(
            request=request,
            name="readiness.html",
            context={"tenant_id": tenant_id, "checks": checks},
        )

    @app.get("/notes/history", response_class=HTMLResponse)
    def notes_history(
        request: Request,
        tenant_id: str = Query("default"),
        viewer_id: str = Query(""),
        is_admin: bool = Query(False),
        limit: int = Query(100, ge=1, le=1000),
        date: str = Query(""),
        organizer: str = Query(""),
        status: str = Query(""),
        transcript_source: str = Query(""),
        upload_status: str = Query(""),
    ) -> HTMLResponse:
        filters = {
            "date": date,
            "organizer": organizer,
            "status": status,
            "transcript_source": transcript_source,
            "upload_status": upload_status,
        }
        notes = _service().list_notes(
            tenant_id=tenant_id,
            viewer_id=viewer_id,
            is_admin=is_admin,
            filters=filters,
            limit=limit,
        )
        microsoft_connected = _service().check_microsoft_connected(viewer_id)
        return templates.TemplateResponse(
            request=request,
            name="notes_history.html",
            context={
                "tenant_id": tenant_id,
                "viewer_id": viewer_id,
                "is_admin": is_admin,
                "filters": filters,
                "notes": notes,
                "microsoft_connected": microsoft_connected,
            },
        )

    @app.get("/notes/meetings/{meeting_job_id}", response_class=HTMLResponse)
    def note_detail(
        request: Request,
        meeting_job_id: str,
        tenant_id: str = Query("default"),
        viewer_id: str = Query(""),
        is_admin: bool = Query(False),
    ) -> HTMLResponse:
        detail = _service().get_note_detail(
            tenant_id=tenant_id,
            meeting_job_id=meeting_job_id,
            viewer_id=viewer_id,
            is_admin=is_admin,
        )
        if not detail:
            raise HTTPException(status_code=404, detail="Meeting notes not found")
        microsoft_connected = _service().check_microsoft_connected(viewer_id)
        return templates.TemplateResponse(
            request=request,
            name="meeting_detail.html",
            context={
                "tenant_id": tenant_id,
                "viewer_id": viewer_id,
                "is_admin": is_admin,
                "detail": detail,
                "microsoft_connected": microsoft_connected,
            },
        )

    @app.get("/notes/meetings/{meeting_job_id}/download/{fmt}")
    def download_note(
        meeting_job_id: str,
        fmt: str,
        tenant_id: str = Query("default"),
        viewer_id: str = Query(""),
        is_admin: bool = Query(False),
    ) -> Response:
        detail = _service().get_note_detail(
            tenant_id=tenant_id,
            meeting_job_id=meeting_job_id,
            viewer_id=viewer_id,
            is_admin=is_admin,
        )
        if not detail:
            raise HTTPException(status_code=404, detail="Meeting notes not found")
        try:
            export = _service().build_download(detail, fmt)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        headers = {"Content-Disposition": f'attachment; filename="{export["filename"]}"'}
        return Response(content=export["content"], media_type=export["content_type"], headers=headers)

    @app.get("/auth/sign-in", response_class=HTMLResponse)
    def sign_in_page(request: Request, magic_link_sent: bool = Query(False)) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="sign_in.html",
            context={"magic_link_sent": magic_link_sent, "email": ""},
        )

    @app.post("/auth/sign-in/magic-link", response_class=HTMLResponse)
    def send_magic_link(request: Request, email: str = Form(...)) -> HTMLResponse:
        _service()._append_audit(
            AuditEvent(
                event_type="auth.magic_link_requested",
                actor_email=email,
                resource_type="auth_request",
                metadata={"method": "magic_link"},
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="sign_in.html",
            context={"magic_link_sent": True, "email": email},
        )

    @app.get("/auth/sign-in/social", response_class=HTMLResponse)
    def social_sign_in(
        request: Request,
        provider: str = Query(...),
        user_id: str = Query(""),
        email: str = Query(""),
        display_name: str = Query(""),
    ) -> HTMLResponse:
        normalized_provider = provider.lower().strip()
        if normalized_provider not in SUPPORTED_SOCIAL_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_SOCIAL_PROVIDERS))
            raise HTTPException(status_code=400, detail=f"Unsupported social provider. Supported providers: {supported}")
        if user_id:
            _service().upsert_user_profile(user_id, email=email, display_name=display_name)
        _service()._append_audit(
            AuditEvent(
                event_type="auth.social_sign_in_requested",
                actor_id=user_id or None,
                actor_email=email or None,
                resource_type="auth_request",
                metadata={"provider": normalized_provider},
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="sign_in.html",
            context={"magic_link_sent": False, "email": email},
        )

    @app.get("/auth/account", response_class=HTMLResponse)
    def account_page(request: Request, user_id: str = Query("")) -> HTMLResponse:
        profile = _service().get_user_profile(user_id)
        connections = _service().list_microsoft_connections(user_id)
        return templates.TemplateResponse(
            request=request,
            name="account.html",
            context={
                "user_id": user_id,
                "profile": profile,
                "microsoft_connections": connections,
                "disconnected": False,
            },
        )

    @app.post("/auth/microsoft/disconnect", response_class=HTMLResponse)
    def disconnect_microsoft_post(
        request: Request,
        user_id: str = Form(...),
        connection_id: str = Form(...),
    ) -> HTMLResponse:
        _service().disconnect_microsoft(user_id, connection_id)
        profile = _service().get_user_profile(user_id)
        connections = _service().list_microsoft_connections(user_id)
        return templates.TemplateResponse(
            request=request,
            name="account.html",
            context={
                "user_id": user_id,
                "profile": profile,
                "microsoft_connections": connections,
                "disconnected": True,
            },
        )

    @app.get("/auth/microsoft/connect", response_class=HTMLResponse)
    def connect_microsoft(
        request: Request,
        user_id: str = Query(""),
        microsoft_user_oid: str = Query(""),
        email: str = Query(""),
        display_name: str = Query(""),
        tenant_id: str = Query(""),
        access_token_ref: str = Query(""),
        refresh_token_ref: str = Query(""),
    ) -> HTMLResponse:
        if user_id and microsoft_user_oid:
            _service().connect_microsoft(
                user_id,
                microsoft_user_oid=microsoft_user_oid,
                email=email,
                display_name=display_name,
                tenant_id=tenant_id,
                access_token=access_token_ref,
                refresh_token=refresh_token_ref,
            )
        profile = _service().get_user_profile(user_id)
        connections = _service().list_microsoft_connections(user_id)
        return templates.TemplateResponse(
            request=request,
            name="account.html",
            context={
                "user_id": user_id,
                "profile": profile,
                "microsoft_connections": connections,
                "disconnected": False,
            },
        )

    return app


app = create_app()
