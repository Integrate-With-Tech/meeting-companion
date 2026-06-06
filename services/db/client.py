"""
Supabase client factory.

The client is created from environment variables and cached for the lifetime
of the process.  Callers should always obtain the client through
``get_client()`` rather than constructing it directly.

Required environment variables:
    SUPABASE_URL  – Project URL, e.g. https://<project-ref>.supabase.co
    SUPABASE_KEY  – Service-role secret key (never expose to browsers).

The service-role key is used deliberately: v1 design forbids direct browser
access to the database; all access goes through the backend service.
"""

import os
from typing import Optional

# The supabase package is an optional runtime dependency.  The repository layer
# accepts any object with a .table() method, so tests can inject a mock without
# installing the real package.
try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover
    Client = None  # type: ignore[assignment,misc]
    create_client = None  # type: ignore[assignment]

_client: Optional[object] = None


def get_client() -> "Client":
    """Return a cached Supabase :class:`~supabase.Client` instance.

    Reads ``SUPABASE_URL`` and ``SUPABASE_KEY`` from the environment on the
    first call and caches the result for subsequent calls.

    Raises
    ------
    RuntimeError
        If either environment variable is missing.
    ImportError
        If the ``supabase`` package is not installed.
    """
    global _client

    if _client is not None:
        return _client  # type: ignore[return-value]

    if create_client is None:
        raise ImportError("The 'supabase' package is required. Install it with: pip install supabase")

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url:
        raise RuntimeError("SUPABASE_URL environment variable is not set. Set it to your Supabase project URL.")
    if not key:
        raise RuntimeError("SUPABASE_KEY environment variable is not set. Set it to your Supabase service-role key.")

    _client = create_client(url, key)
    return _client  # type: ignore[return-value]


def _reset_client() -> None:
    """Clear the cached client.  For use in tests only."""
    global _client
    _client = None
