from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

router = Router(name="f_respects")

_F_AUDIO_FILE = Path(__file__).parents[3] / "assets" / "F" / "F.mp3"
_WINDOW = timedelta(minutes=10)
_COOLDOWN = timedelta(minutes=10)
_MIN_F_MESSAGES = 3


@dataclass
class _ChatFState:
    last_f_message_id: int | None = None
    consecutive_f_count: int = 0
    f_timestamps: deque[datetime] = field(default_factory=deque)
    last_trigger_at: datetime | None = None


_chat_states: dict[int, _ChatFState] = {}


def _is_plain_f(text: str | None) -> bool:
    return bool(text and text.strip().upper() == "F")


def _trim_window(state: _ChatFState, now: datetime) -> None:
    while state.f_timestamps and now - state.f_timestamps[0] > _WINDOW:
        state.f_timestamps.popleft()


@router.message(F.text.func(_is_plain_f))
async def on_f_respects(message: Message) -> None:
    now = datetime.utcnow()
    state = _chat_states.setdefault(message.chat.id, _ChatFState())

    if state.last_f_message_id is not None and message.message_id == state.last_f_message_id + 1:
        state.consecutive_f_count += 1
    else:
        state.consecutive_f_count = 1
    state.last_f_message_id = message.message_id

    state.f_timestamps.append(now)
    _trim_window(state, now)

    hit_consecutive_threshold = state.consecutive_f_count >= _MIN_F_MESSAGES
    hit_window_threshold = len(state.f_timestamps) >= _MIN_F_MESSAGES
    if not (hit_consecutive_threshold or hit_window_threshold):
        return

    if state.last_trigger_at and now - state.last_trigger_at < _COOLDOWN:
        return

    await message.reply_audio(
        audio=FSInputFile(_F_AUDIO_FILE),
        disable_notification=True,
    )
    state.last_trigger_at = now
