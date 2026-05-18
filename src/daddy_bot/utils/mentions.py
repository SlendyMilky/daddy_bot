"""Shared helpers for building HTML Telegram user mentions."""
from __future__ import annotations

import html


def mention_html(user_id: int, label: str) -> str:
    """Render an HTML mention link compatible with Telegram parse_mode='HTML'."""
    return f'<a href="tg://user?id={user_id}">{html.escape(label)}</a>'


def label_for(first_name: str | None, username: str | None, fallback: str = "Copain") -> str:
    """Compute the display label for a user: @username if present, else first_name, else fallback."""
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return fallback
