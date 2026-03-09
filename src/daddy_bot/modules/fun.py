import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="fun")

NINEBALL_ANSWERS = [
    "Oui.",
    "Non.",
    "Peut-etre.",
    "Repose la question plus tard.",
    "Papa dit: fais-le.",
    "Papa dit: mauvaise idee.",
]

THINK_LINES = [
    "Respire. Observe. Agis.",
    "Un petit pas propre vaut mieux qu'un grand bazar.",
    "Commence simple, optimise ensuite.",
]

COCKTAILS = [
    "Mojito",
    "Moscow Mule",
    "Old Fashioned",
    "Negroni",
    "Gin Tonic",
]


@router.message(Command("nineball"))
async def on_nineball(message: Message) -> None:
    await message.answer(random.choice(NINEBALL_ANSWERS), disable_notification=True)


@router.message(Command("think"))
async def on_think(message: Message) -> None:
    await message.answer(random.choice(THINK_LINES), disable_notification=True)


@router.message(Command("cocktail"))
async def on_cocktail(message: Message) -> None:
    await message.answer(f"Suggestion du jour: {random.choice(COCKTAILS)}", disable_notification=True)
