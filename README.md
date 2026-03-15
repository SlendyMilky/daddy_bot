# Daddy Bot (Python aiogram)

Daddy is a modular Telegram bot migrated from n8n to Python.

## Quick start

1. Create and activate a virtual environment.
2. Install project dependencies:
   - `pip install -e .`
3. Copy `.env.example` to `.env` and set at least:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY` (optional for `/start`)
   - `GOOGLE_MAPS_API_KEY` (required for `/bibine <lieu>` place search)
4. Run:
   - `python -m daddy_bot.main`

## Project structure

- `src/daddy_bot/main.py`: bot bootstrap and polling.
- `src/daddy_bot/core/`: config, logging, rate limiting, router registry, error handlers.
- `src/daddy_bot/modules/`: independent command/trigger modules.
- `src/daddy_bot/services/`: external providers (OpenAI, etc.).
- `src/daddy_bot/utils/`: shared regex patterns and helpers.

## Migrated in V1

- Commands: `/start`, `/help`, `/cocktail`, `/think`, `/nineball`, `/bibine`, `/bibine_test`
- Auto triggers: `erika`, `shalom`, `quoi`, `peur`, `women`, location, time callback
- Stubs: `/unlock`, `/s2t`, `/i2t`, `/resume`, `/t2i`, `/t2s`
- Social route stubs: twitter/x, tiktok, instagram URL/callback detections

## Manual validation checklist

- `/start` returns a short welcome text.
- `/help` returns support information.
- Send `quoi` and get `Feur.`.
- Send a location and get a migration acknowledgment.
- Run `/unlock` and verify stub response.
- Run `/nineball` and verify random answer.
- Run `/bibine` twice and verify subscribe/unsubscribe responses.
- Run `/bibine L'imprevu` and verify place proposal + map location; add a second place to verify location poll creation.
- Verify bibine reminder is posted once per week at random time (Thu 15-22 or Fri 09-17).
- Spam quickly to trigger rate limit cooldown message.
