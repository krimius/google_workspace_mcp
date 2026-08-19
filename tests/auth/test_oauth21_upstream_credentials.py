"""Credentials built from FastMCP 3.4.2's upstream token store.

The engine used to read three attributes off the auth provider
(``_access_tokens``, ``_access_to_refresh``, ``_refresh_tokens``) that do not
exist in FastMCP 3.4.2. ``getattr(..., default)`` swallowed the miss, so every
Google credential was built with ``refresh_token=None`` and died the moment
Google's access token aged out. These tests pin the replacement chain
(jti -> ``_jti_mapping_store`` -> ``_upstream_token_store``) and guard against
the dead attribute names coming back.
"""

import inspect
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import auth.oauth21_session_store as session_store

DEAD_PROVIDER_ATTRIBUTES = ("_access_tokens", "_access_to_refresh", "_refresh_tokens")


class _FakeStore:
    """Stand-in for FastMCP's PydanticAdapter, whose get() is async."""

    def __init__(self, entries):
        self._entries = entries

    async def get(self, key):
        return self._entries.get(key)


class _FakeProviderBase:
    """Provider shaped like FastMCP 3.4.2's OAuthProxy / GoogleProvider."""

    def __init__(self, upstream_token_set, jti="jti-abc", upstream_token_id="ut-1"):
        self.jwt_issuer = SimpleNamespace(verify_token=lambda token: {"jti": jti})
        self._jti_mapping_store = _FakeStore(
            {jti: SimpleNamespace(upstream_token_id=upstream_token_id)}
        )
        self._upstream_token_store = _FakeStore({upstream_token_id: upstream_token_set})
        self._upstream_client_id = "client-id-from-provider"
        self._upstream_client_secret = SimpleNamespace(
            get_secret_value=lambda: "client-secret-from-provider"
        )


class _StrictFakeProvider(_FakeProviderBase):
    """Fails loudly if anything reaches for the retired attribute names."""

    def __getattr__(self, name):
        if name in DEAD_PROVIDER_ATTRIBUTES:
            raise AssertionError(
                f"provider attribute {name!r} was read; it does not exist in "
                "FastMCP 3.4.2 and must never be consulted again"
            )
        raise AttributeError(name)


def _upstream_token_set(refresh_token="1//google-refresh-token", expires_at=None):
    return SimpleNamespace(
        upstream_token_id="ut-1",
        access_token="ya29.google-access-token",
        refresh_token=refresh_token,
        refresh_token_expires_at=None,
        expires_at=expires_at if expires_at is not None else time.time() + 3600,
        token_type="Bearer",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        client_id="mcp-client",
        created_at=time.time(),
        raw_token_data={},
    )


def _access_token():
    return SimpleNamespace(
        token="fastmcp-issued-token",
        client_id="mcp-client",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        expires_at=int(time.time()) + 60,
        claims={"email": "krim@lomacommunications.com"},
    )


@pytest.fixture
def bearer_header(monkeypatch):
    """Serve a FastMCP-issued bearer token on the current request."""
    observed = {}

    def fake_get_http_headers(*args, **kwargs):
        observed["kwargs"] = kwargs
        return {"authorization": "Bearer fastmcp.jwt.token"}

    monkeypatch.setattr(
        "auth.oauth21_session_store.get_http_headers", fake_get_http_headers
    )
    return observed


@pytest.mark.asyncio
async def test_credentials_carry_the_four_refresh_fields(monkeypatch, bearer_header):
    """google-auth needs refresh_token, token_uri, client_id and client_secret."""
    expires_at = time.time() + 1800
    provider = _FakeProviderBase(_upstream_token_set(expires_at=expires_at))
    monkeypatch.setattr(session_store, "_auth_provider", provider)

    credentials = await session_store._build_credentials_from_provider(_access_token())

    assert credentials is not None
    assert credentials.refresh_token == "1//google-refresh-token"
    assert credentials.token_uri == "https://oauth2.googleapis.com/token"
    assert credentials.client_id == "client-id-from-provider"
    assert credentials.client_secret == "client-secret-from-provider"

    # The Google access token and Google's own expiry, not FastMCP's.
    # google-auth wants expiry as naive UTC, which is what the store normalizes to.
    assert credentials.token == "ya29.google-access-token"
    assert credentials.expiry is not None
    assert credentials.expiry.tzinfo is None
    expected = datetime.fromtimestamp(expires_at, tz=timezone.utc).replace(tzinfo=None)
    assert abs((credentials.expiry - expected).total_seconds()) < 2
    assert credentials.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]

    assert bearer_header["kwargs"] == {"include": {"authorization"}}


@pytest.mark.asyncio
async def test_dead_attribute_names_are_never_read(monkeypatch, bearer_header):
    """Regression: the three FastMCP 2.x attribute names must not be consulted."""
    provider = _StrictFakeProvider(_upstream_token_set())
    monkeypatch.setattr(session_store, "_auth_provider", provider)

    credentials = await session_store._build_credentials_from_provider(_access_token())

    assert credentials is not None
    assert credentials.refresh_token == "1//google-refresh-token"


def test_dead_attribute_names_are_absent_from_the_source():
    """Regression: the retired names must not reappear anywhere in the module."""
    source = Path(session_store.__file__).read_text(encoding="utf-8")
    for name in DEAD_PROVIDER_ATTRIBUTES:
        assert f'"{name}"' not in source, f"{name} is read again in the session store"


@pytest.mark.asyncio
async def test_missing_upstream_token_set_degrades_without_raising(
    monkeypatch, bearer_header
):
    """No stored token set means no refresh token, not a crash."""
    provider = _FakeProviderBase(None)
    monkeypatch.setattr(session_store, "_auth_provider", provider)

    credentials = await session_store._build_credentials_from_provider(_access_token())

    assert credentials is not None
    assert credentials.refresh_token is None
    assert credentials.token == "fastmcp-issued-token"


@pytest.mark.asyncio
async def test_raw_google_bearer_is_not_treated_as_a_fastmcp_jwt(monkeypatch):
    """A ya29.* bearer has no jti, so no upstream lookup is attempted."""
    monkeypatch.setattr(
        "auth.oauth21_session_store.get_http_headers",
        lambda *args, **kwargs: {"authorization": "Bearer ya29.direct-google-token"},
    )
    provider = _FakeProviderBase(_upstream_token_set())
    monkeypatch.setattr(session_store, "_auth_provider", provider)

    assert session_store._extract_fastmcp_token_jti(provider) is None

    credentials = await session_store._build_credentials_from_provider(_access_token())
    assert credentials is not None
    assert credentials.refresh_token is None


def test_credential_entry_points_are_async():
    """The upstream stores are async, so both entry points must be coroutines."""
    assert inspect.iscoroutinefunction(session_store._build_credentials_from_provider)
    assert inspect.iscoroutinefunction(session_store.ensure_session_from_access_token)
    assert inspect.iscoroutinefunction(session_store._resolve_upstream_token_set)
