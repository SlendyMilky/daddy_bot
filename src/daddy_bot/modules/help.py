from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="help")


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(
        "Besoin d'aide ?\n\nEnvoie un message a @daddy_v2_support_bot",
        disable_notification=False,
    )
