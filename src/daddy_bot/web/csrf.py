"""CSRF token helpers using itsdangerous, tied to the session sid."""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer


def _signer(secret_key: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret_key, salt="csrf")


def generate_csrf_token(secret_key: str, sid: str) -> str:
    return _signer(secret_key).dumps(sid)


def validate_csrf_token(secret_key: str, sid: str, token: str) -> bool:
    try:
        payload = _signer(secret_key).loads(token)
        return payload == sid
    except BadSignature:
        return False
