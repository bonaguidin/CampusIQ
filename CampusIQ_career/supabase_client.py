"""Builds a Supabase client scoped to a caller's own session.

Every client this module returns runs under the caller-supplied access
token, so Postgres RLS applies exactly as it would for that user's own
request. This module never reads or references SUPABASE_SECRET_KEY —
doing so here would be a bug, since it would let a request path bypass
RLS.
"""

import os

from supabase import Client, create_client


class SupabaseConfigError(RuntimeError):
    """Raised when required Supabase configuration is missing."""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SupabaseConfigError(f"{name} is not set.")
    return value


def build_client_for_token(access_token: str) -> Client:
    """Return a Supabase client whose requests run under `access_token`.

    Uses SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY only. The publishable
    key identifies the project (the `apikey` header); `access_token` is
    the caller's own session token, carried as the `Authorization`
    bearer token, so `auth.uid()` and RLS resolve to that specific user
    -- never an admin/service-role identity.
    """
    if not access_token or not access_token.strip():
        raise SupabaseConfigError("access_token is required.")

    url = _required_env("SUPABASE_URL")
    publishable_key = _required_env("SUPABASE_PUBLISHABLE_KEY")

    client = create_client(url, publishable_key)
    client.postgrest.auth(access_token)
    return client
