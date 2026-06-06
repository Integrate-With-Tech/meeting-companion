"""
Database sub-package for Supabase/Postgres access.

Provides:
    - client  : Supabase client factory (``get_client``).
    - models  : Python dataclasses mirroring each database table.
    - repository : CRUD operations for every table.

Usage::

    from services.db import get_client
    from services.db.repository import MeetingJobRepository

    client = get_client()
    repo   = MeetingJobRepository(client)
    job    = repo.create(tenant_id="abc123", source_type="teams_native")
"""

from services.db.client import get_client

__all__ = ["get_client"]
