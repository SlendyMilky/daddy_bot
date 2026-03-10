import html
import json
import logging
import random
from pathlib import Path

import httpx
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from openai import AsyncOpenAI

from daddy_bot.core.config import get_settings

logger = logging.getLogger(__name__)

router = Router(name="fun")

_NINEBALL_PATH = Path(__file__).parents[3] / "assets" / "nineball" / "Daddy_Nineball.json"
_NINEBALL_ENTRIES: list[str] = []
try:
    _raw = json.loads(_NINEBALL_PATH.read_text(encoding="utf-8"))
    _NINEBALL_ENTRIES = [e["Text"] for e in _raw.get("Daddy_Nineball", []) if e.get("Text")]
except Exception as _exc:
    logger.warning("Could not load Daddy_Nineball.json: %s", _exc)

_REDDIT_SHOWERTHOUGHTS_URL = "https://www.reddit.com/r/Showerthoughts/hot.json"
_THINK_TRANSLATE_SYSTEM = (
    "Tu n'as qu'un seul et unique but : traduire en français le message que tu reçois. "
    "Comprends le sens et traduis en conséquence. "
    "Réponds UNIQUEMENT par la traduction, rien d'autre."
)

_COCKTAILDB_URL = "https://www.thecocktaildb.com/api/json/v1/1/random.php"
_TRANSLATE_SYSTEM = (
    "Tu es un traducteur français. "
    "Réponds UNIQUEMENT en JSON valide avec les clés \"verre\", \"ingredients\", \"instructions\". "
    "Traduis chaque champ en français et convertis toutes les mesures en système métrique."
)


def _parse_ingredients(drink: dict) -> str:
    parts = []
    for i in range(1, 16):
        ingredient = (drink.get(f"strIngredient{i}") or "").strip()
        measure = (drink.get(f"strMeasure{i}") or "").strip()
        if ingredient:
            parts.append(f"{measure} {ingredient}".strip() if measure else ingredient)
    return ", ".join(parts)


@router.message(Command("nineball"))
async def on_nineball(message: Message) -> None:
    if not _NINEBALL_ENTRIES:
        await message.reply("Aucune réponse disponible.", disable_notification=True)
        return
    text = random.choice(_NINEBALL_ENTRIES)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    await message.answer(text, parse_mode="HTML", disable_notification=True)


@router.message(Command("think"))
async def on_think(message: Message) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": "daddy_bot/1.0 (by u/daddy_v2_bot)"},
        ) as client:
            resp = await client.get(_REDDIT_SHOWERTHOUGHTS_URL, params={"limit": 50})
            resp.raise_for_status()

        posts = [
            p["data"]
            for p in resp.json()["data"]["children"]
            if not p["data"].get("stickied") and p["data"].get("title")
        ]
        if not posts:
            await message.reply("Aucun post trouvé sur r/Showerthoughts.", disable_notification=True)
            return

        post = random.choice(posts)
        title_en = post["title"]
        post_url = f"https://reddit.com{post['permalink']}"
        upvotes = post.get("ups", 0)
        from datetime import datetime, timezone
        created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
        date_str = created.strftime("%d.%m.%y")

        settings = get_settings()
        if settings.openai_api_key:
            client_ai = AsyncOpenAI(api_key=settings.openai_api_key)
            gpt_resp = await client_ai.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": _THINK_TRANSLATE_SYSTEM},
                    {"role": "user", "content": title_en},
                ],
            )
            title_fr = (gpt_resp.choices[0].message.content or title_en).strip()
        else:
            title_fr = title_en

        text = (
            f"🇨🇭 - {html.escape(title_fr)}\n\n"
            f"🇬🇧 - {html.escape(title_en)}\n"
            f'<a href="{post_url}">🌐 Reddit  📆 {date_str}  ⬆️ {upvotes:,}</a>'
        )
        await message.reply(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=True,
        )
    except Exception as exc:
        logger.exception("think failed: %s", exc)
        await message.reply("Erreur lors de la récupération du post.", disable_notification=True)


@router.message(Command("cocktail"))
async def on_cocktail(message: Message) -> None:
    status_msg = await message.answer(
        "<i>Génération en cours...</i>", parse_mode="HTML", disable_notification=True
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_COCKTAILDB_URL)
            resp.raise_for_status()
        drink = resp.json()["drinks"][0]

        name = drink.get("strDrink", "?")
        drink_id = drink.get("idDrink", "")
        thumb_url = drink.get("strDrinkThumb", "")
        glass_en = drink.get("strGlass", "")
        instructions_en = drink.get("strInstructions", "")
        ingredients_en = _parse_ingredients(drink)

        settings = get_settings()
        if settings.openai_api_key:
            import json as _json
            client_ai = AsyncOpenAI(api_key=settings.openai_api_key)
            gpt_resp = await client_ai.chat.completions.create(
                model="gpt-4.1-nano",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _TRANSLATE_SYSTEM},
                    {"role": "user", "content": _json.dumps({
                        "verre": glass_en,
                        "ingredients": ingredients_en,
                        "instructions": instructions_en,
                    }, ensure_ascii=False)},
                ],
            )
            data = _json.loads(gpt_resp.choices[0].message.content or "{}")
            glass = data.get("verre") or glass_en
            ingredients = data.get("ingredients") or ingredients_en
            instructions = data.get("instructions") or instructions_en
        else:
            glass, ingredients, instructions = glass_en, ingredients_en, instructions_en

        name_esc = html.escape(name)
        source_url = f"https://www.thecocktaildb.com/drink/{drink_id}"
        caption = (
            f'🍹 - <a href="{source_url}"><b><u>{name_esc}</u></b></a>\n\n'
            f"<b>🥂 - Type de verre</b>\n<i>{html.escape(glass)}</i>\n\n"
            f"<b>📖 - Ingrédients</b>\n<i>{html.escape(ingredients)}</i>\n\n"
            f"<b>📝 - Instructions</b>\n<i>{html.escape(instructions)}</i>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📷 Photo FHD", url=thumb_url),
        ]]) if thumb_url else None

        await status_msg.delete()
        await message.answer_photo(
            photo=f"{thumb_url}/preview" if thumb_url else thumb_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_notification=True,
        )
    except Exception as exc:
        logger.exception("cocktail failed: %s", exc)
        await status_msg.edit_text("Erreur lors de la récupération du cocktail.", parse_mode="HTML")
