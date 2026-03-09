from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from daddy_bot.utils.patterns import I2T_RE, RESUME_RE, S2T_RE, T2I_RE, T2S_RE, UNLOCK_RE

router = Router(name="utility")


def _full_text(message: Message) -> str:
    return f"{message.text or ''}{message.caption or ''}".strip()


async def _send_stub(message: Message, module_name: str) -> None:
    await message.answer(
        f"Le module `{module_name}` est en cours de migration depuis n8n.",
        disable_notification=True,
    )


@router.message(Command("unlock"))
@router.message(F.text.func(lambda value: bool(value and UNLOCK_RE.search(value))))
async def on_unlock(message: Message) -> None:
    await _send_stub(message, "unlock")


@router.message(Command("s2t"))
@router.message(F.text.func(lambda value: bool(value and S2T_RE.search(value))))
async def on_s2t(message: Message) -> None:
    await _send_stub(message, "s2t")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(I2T_RE.search(_full_text(message))))
)
async def on_i2t(message: Message) -> None:
    await _send_stub(message, "i2t")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(RESUME_RE.search(_full_text(message))))
)
async def on_resume(message: Message) -> None:
    await _send_stub(message, "resume")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(T2I_RE.search(_full_text(message))))
)
async def on_t2i_message(message: Message) -> None:
    await _send_stub(message, "t2i")


@router.callback_query(F.data.contains("t2i"))
async def on_t2i_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(
            "Le module `t2i` est en cours de migration depuis n8n.",
            disable_notification=True,
        )
    await callback.answer()


@router.message(
    F.func(
        lambda message: isinstance(message, Message)
        and bool(message.reply_to_message)
        and "Description de l'image a generer ?" in ((message.reply_to_message.text or ""))
    )
)
async def on_t2i_reply_chain(message: Message) -> None:
    await _send_stub(message, "t2i")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(T2S_RE.search(_full_text(message))))
)
async def on_t2s_message(message: Message) -> None:
    await _send_stub(message, "t2s")


@router.callback_query(F.data.contains("t2s"))
async def on_t2s_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(
            "Le module `t2s` est en cours de migration depuis n8n.",
            disable_notification=True,
        )
    await callback.answer()
