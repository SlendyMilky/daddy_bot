"""Tests for web auth: OIDC helpers, session gate, owner gating, CSRF."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from daddy_bot.services.telegram_oidc import TelegramOIDCClient, _code_challenge, generate_pkce_pair
from daddy_bot.web.csrf import generate_csrf_token, validate_csrf_token
from daddy_bot.web.sessions import sign_session_id, unsign_session_id

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def test_pkce_pair_lengths():
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43


def test_code_challenge_deterministic():
    verifier = "abc123"
    c1 = _code_challenge(verifier)
    c2 = _code_challenge(verifier)
    assert c1 == c2
    assert c1 != verifier


def test_code_challenge_base64url_no_padding():
    verifier = "testverifier"
    challenge = _code_challenge(verifier)
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


# ---------------------------------------------------------------------------
# Session cookie signing
# ---------------------------------------------------------------------------


def test_sign_unsign_round_trip():
    key = "supersecret"
    sid = "mysessionid123"
    signed = sign_session_id(key, sid)
    assert signed != sid
    result = unsign_session_id(key, signed)
    assert result == sid


def test_unsign_wrong_key_returns_none():
    signed = sign_session_id("key1", "sid")
    assert unsign_session_id("key2", signed) is None


def test_unsign_garbage_returns_none():
    assert unsign_session_id("key", "not-a-valid-token") is None


# ---------------------------------------------------------------------------
# CSRF token
# ---------------------------------------------------------------------------


def test_csrf_valid():
    key = "secret"
    sid = "session123"
    token = generate_csrf_token(key, sid)
    assert validate_csrf_token(key, sid, token)


def test_csrf_wrong_sid():
    key = "secret"
    token = generate_csrf_token(key, "sid1")
    assert not validate_csrf_token(key, "sid2", token)


def test_csrf_wrong_key():
    token = generate_csrf_token("key1", "sid")
    assert not validate_csrf_token("key2", "sid", token)


def test_csrf_tampered():
    assert not validate_csrf_token("key", "sid", "garbage")


# ---------------------------------------------------------------------------
# OIDC client: build_authorization_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_authorization_url():
    client = TelegramOIDCClient(
        client_id="test_client",
        client_secret="test_secret",
        discovery_url="https://example.com/.well-known/openid-configuration",
        redirect_uri="https://example.com/callback",
    )
    # Mock _load_metadata to avoid network call
    client._metadata = {
        "authorization_endpoint": "https://example.com/auth",
        "token_endpoint": "https://example.com/token",
        "jwks_uri": "https://example.com/jwks",
        "_fetched_at": time.monotonic(),
    }
    client._metadata_fetched_at = time.monotonic()

    verifier, challenge = generate_pkce_pair()
    url = await client.build_authorization_url(state="mystate", code_verifier=verifier)

    assert "https://example.com/auth" in url
    assert "client_id=test_client" in url
    assert "state=mystate" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "scope=openid" in url


# ---------------------------------------------------------------------------
# OIDC client: exchange_code validates JWT claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_aud_mismatch():
    """exchange_code raises ValueError when JWT aud doesn't match client_id."""
    from authlib.jose import JsonWebKey
    from authlib.jose import jwt as authlib_jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = JsonWebKey.import_key(private_key, {"kty": "RSA", "use": "sig", "kid": "testkey"})
    public_jwk = JsonWebKey.import_key(
        private_key.public_key(), {"kty": "RSA", "use": "sig", "kid": "testkey"}
    )

    now = int(time.time())
    payload = {
        "sub": "123456",
        "iss": "https://id.telegram.org",
        "aud": "wrong_client",  # wrong aud
        "iat": now,
        "exp": now + 300,
    }
    header = {"alg": "RS256", "kid": "testkey"}
    id_token = authlib_jwt.encode(header, payload, jwk).decode()

    client = TelegramOIDCClient(
        client_id="correct_client",
        client_secret="secret",
        discovery_url="https://example.com/.well-known/openid-configuration",
        redirect_uri="https://example.com/callback",
    )
    client._metadata = {
        "authorization_endpoint": "https://example.com/auth",
        "token_endpoint": "https://example.com/token",
        "jwks_uri": "https://example.com/jwks",
        "_fetched_at": time.monotonic(),
    }
    client._metadata_fetched_at = time.monotonic()

    key_set_data = {"keys": [public_jwk.as_dict()]}
    from authlib.jose import JsonWebKey as JWK

    client._jwks = JWK.import_key_set(key_set_data)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"id_token": id_token}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(ValueError, match="aud mismatch"):
            await client.exchange_code(code="authcode", code_verifier="verifier")


@pytest.mark.asyncio
async def test_exchange_code_expired_token():
    """exchange_code raises an error for an expired JWT."""
    from authlib.jose import JsonWebKey
    from authlib.jose import jwt as authlib_jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = JsonWebKey.import_key(private_key, {"kty": "RSA", "use": "sig", "kid": "k1"})
    public_jwk = JsonWebKey.import_key(private_key.public_key(), {"kty": "RSA", "use": "sig", "kid": "k1"})

    now = int(time.time())
    payload = {
        "sub": "123",
        "iss": "https://id.telegram.org",
        "aud": "client",
        "iat": now - 3600,
        "exp": now - 1800,  # expired
    }
    header = {"alg": "RS256", "kid": "k1"}
    id_token = authlib_jwt.encode(header, payload, jwk).decode()

    client = TelegramOIDCClient(
        client_id="client",
        client_secret="secret",
        discovery_url="https://example.com/.well-known/openid-configuration",
        redirect_uri="https://example.com/callback",
    )
    client._metadata = {
        "token_endpoint": "https://example.com/token",
        "_fetched_at": time.monotonic(),
    }
    client._metadata_fetched_at = time.monotonic()
    client._jwks = JsonWebKey.import_key_set({"keys": [public_jwk.as_dict()]})

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"id_token": id_token}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(Exception):  # ExpiredTokenError or similar from authlib
            await client.exchange_code(code="code", code_verifier="v")


# ---------------------------------------------------------------------------
# Web: protected route redirects without cookie
# ---------------------------------------------------------------------------


@pytest.fixture()
async def admin_app():
    """Create a minimal admin FastAPI app bound to an in-memory DB."""
    import aiosqlite

    from daddy_bot.core import db as db_module

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")

    migrations_dir = Path(__file__).parent.parent / "src/daddy_bot/db/migrations"
    sql = (migrations_dir / "0001_init.sql").read_text()
    await conn.executescript(sql)
    await conn.commit()
    db_module._connection = conn  # type: ignore[attr-defined]

    settings = MagicMock()
    settings.admin_web_secret_key = "testsecretkey123"
    settings.admin_web_public_url = "http://localhost:8080"
    settings.telegram_oidc_client_id = None
    settings.telegram_oidc_client_secret = None
    settings.telegram_oidc_discovery_url = "https://example.com/.well-known/openid-configuration"
    settings.admin_session_ttl_hours = 168
    settings.owner_id_set.return_value = {999}
    settings.princesse_morning_chat_id_tuple.return_value = ()

    with patch("daddy_bot.core.config.get_settings", return_value=settings):
        with patch("daddy_bot.web.app._resolve_secret_key", return_value="testsecretkey123"):
            from daddy_bot.web.app import create_admin_app

            app = create_admin_app(bot=None, settings=settings)
            app.state.secret_key = "testsecretkey123"
            app.state.settings = settings

    yield app

    await conn.close()
    db_module._connection = None  # type: ignore[attr-defined]


def test_protected_route_redirects_without_cookie(admin_app):
    with TestClient(admin_app, follow_redirects=False) as client:
        resp = client.get("/admin/")
    assert resp.status_code in (302, 307)
    assert "/admin/login" in resp.headers.get("location", "")


def test_healthz_public(admin_app):
    with TestClient(admin_app) as client:
        resp = client.get("/admin/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_no_oidc_returns_503(admin_app):
    with TestClient(admin_app) as client:
        resp = client.get("/admin/login")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_owner_dependency_non_owner_forbidden(tmp_path: Path):
    """require_owner returns 403 when user_id is not in OWNER_IDS."""
    import aiosqlite

    from daddy_bot.core import db as db_module

    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA journal_mode=WAL")
    migrations_dir = Path(__file__).parent.parent / "src/daddy_bot/db/migrations"
    sql = (migrations_dir / "0001_init.sql").read_text()
    await conn.executescript(sql)
    await conn.commit()
    db_module._connection = conn  # type: ignore[attr-defined]

    from daddy_bot.web.sessions import create_session, sign_session_id

    # Create a session for user 42 (not in OWNER_IDS)
    sid = await create_session(user_id=42, ttl_hours=1)
    secret_key = "testsecret"
    signed = sign_session_id(secret_key, sid)

    settings = MagicMock()
    settings.owner_id_set.return_value = {999}  # 42 not in owners
    settings.admin_web_secret_key = secret_key
    settings.admin_web_public_url = "http://localhost"
    settings.telegram_oidc_client_id = None
    settings.telegram_oidc_client_secret = None
    settings.telegram_oidc_discovery_url = "https://example.com/.well-known/openid-configuration"
    settings.admin_session_ttl_hours = 1
    settings.princesse_morning_chat_id_tuple.return_value = ()

    with patch("daddy_bot.core.config.get_settings", return_value=settings):
        with patch("daddy_bot.web.app._resolve_secret_key", return_value=secret_key):
            from daddy_bot.web.app import create_admin_app

            app = create_admin_app(bot=None, settings=settings)
            app.state.secret_key = secret_key
            app.state.settings = settings

    with TestClient(app, follow_redirects=False, cookies={"admin_session": signed}) as client:
        resp = client.get("/admin/")
    assert resp.status_code == 403

    await conn.close()
    db_module._connection = None  # type: ignore[attr-defined]
