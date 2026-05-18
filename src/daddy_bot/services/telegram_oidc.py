"""Telegram OpenID Connect client (PKCE + authlib JWT validation)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from authlib.jose import JsonWebKey, JWTClaims
from authlib.jose import jwt as authlib_jwt

logger = logging.getLogger(__name__)

_METADATA_CACHE_TTL = 3600  # 1 hour


@dataclass(slots=True)
class TelegramIdentity:
    user_id: int
    username: str | None
    first_name: str | None
    photo_url: str | None


def _generate_code_verifier() -> str:
    """Generate a PKCE code verifier (43-128 chars, unreserved chars)."""
    return secrets.token_urlsafe(48)  # 64 chars after base64url


def _code_challenge(verifier: str) -> str:
    """Compute S256 PKCE code challenge."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = _generate_code_verifier()
    return verifier, _code_challenge(verifier)


class TelegramOIDCClient:
    """Minimal OIDC client for Telegram Sign-in (Authorization Code + PKCE S256)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        discovery_url: str,
        redirect_uri: str,
        cache_path: Path | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.discovery_url = discovery_url
        self.redirect_uri = redirect_uri
        self._cache_path = cache_path
        self._metadata: dict[str, Any] | None = None
        self._metadata_fetched_at: float = 0.0
        self._jwks: Any = None  # authlib KeySet

    async def _load_metadata(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._metadata and (now - self._metadata_fetched_at) < _METADATA_CACHE_TTL:
            return self._metadata

        # Try disk cache first
        if self._cache_path and self._cache_path.exists():
            try:
                cached = json.loads(self._cache_path.read_text())
                if now - cached.get("_fetched_at", 0) < _METADATA_CACHE_TTL:
                    self._metadata = cached
                    self._metadata_fetched_at = cached["_fetched_at"]
                    return self._metadata
            except Exception:
                pass

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(self.discovery_url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        data["_fetched_at"] = now
        if self._cache_path:
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_text(json.dumps(data))
            except Exception as exc:
                logger.warning("Could not persist OIDC metadata cache: %s", exc)

        self._metadata = data
        self._metadata_fetched_at = now
        return data

    async def _load_jwks(self) -> Any:
        if self._jwks is not None:
            return self._jwks
        meta = await self._load_metadata()
        jwks_uri = meta["jwks_uri"]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
            jwks_data = resp.json()
        self._jwks = JsonWebKey.import_key_set(jwks_data)
        return self._jwks

    async def build_authorization_url(self, state: str, code_verifier: str) -> str:
        meta = await self._load_metadata()
        auth_endpoint = meta["authorization_endpoint"]
        challenge = _code_challenge(code_verifier)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{auth_endpoint}?{query}"

    async def exchange_code(self, code: str, code_verifier: str) -> TelegramIdentity:
        meta = await self._load_metadata()
        token_endpoint = meta["token_endpoint"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code_verifier": code_verifier,
                },
            )
            resp.raise_for_status()
            token_data: dict[str, Any] = resp.json()

        id_token: str | None = token_data.get("id_token")
        if not id_token:
            raise ValueError("No id_token in token response")

        jwks = await self._load_jwks()
        claims: JWTClaims = authlib_jwt.decode(id_token, jwks)
        claims.validate(now=int(time.time()))
        logger.debug(
            "id_token claims (sub redacted): %s",
            {k: v for k, v in claims.items() if k != "sub"},
        )

        # Validate standard claims
        if claims.get("aud") != self.client_id and self.client_id not in (claims.get("aud") or []):
            raise ValueError(f"id_token aud mismatch: {claims.get('aud')!r}")

        sub = claims.get("sub")
        if not sub:
            raise ValueError("id_token missing sub claim")

        # Telegram's sub is an internal opaque value, not the Telegram user ID.
        # The actual Telegram user ID is in the "id" claim (integer).
        # Fall back to sub only if "id" is absent (forward-compat).
        tg_id = claims.get("id") or claims.get("telegram_id")
        if tg_id is not None:
            user_id = int(tg_id)
        else:
            logger.warning(
                "Telegram id_token has no 'id' claim — falling back to sub=%s. "
                "Full claims (minus sensitive): %s",
                sub,
                {k: v for k, v in claims.items() if k not in ("sub", "nonce")},
            )
            user_id = int(sub)

        return TelegramIdentity(
            user_id=user_id,
            username=claims.get("preferred_username") or claims.get("username"),
            first_name=claims.get("given_name") or claims.get("first_name"),
            photo_url=claims.get("picture"),
        )
