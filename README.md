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
- `src/daddy_bot/core/`: config, logging, rate limiting, router registry, error handlers, SQLite connection.
- `src/daddy_bot/db/`: SQLite migrations and repository layer.
- `src/daddy_bot/modules/`: independent command/trigger modules.
- `src/daddy_bot/services/`: external providers (OpenAI, Telegram OIDC).
- `src/daddy_bot/utils/`: shared regex patterns and helpers.
- `src/daddy_bot/web/`: admin panel (FastAPI + Jinja2 + HTMX + Tailwind).

## Admin panel

The bot ships with a built-in owner-only admin panel served on port `8080` (same process, `asyncio.gather`).

### Features

| Route | Description |
|---|---|
| `/admin/` | Dashboard: chat count, subscriber count, last bibine state, princesse history |
| `/admin/bibine` | Subscribers list + remove, active polls, manual ping, reset weekly state |
| `/admin/princesse` | Pool per chat + remove member, send history, test ritual DM |
| `/admin/broadcast` | Send message to any tracked chat; broadcast log |
| `/admin/logs` | Live log tail via SSE (in-memory ring buffer 1000 lines) |
| `/admin/db` | Paginated read-only table browser |
| `/admin/healthz` | Health check (public) |

### Authentication

Login via Telegram OpenID Connect ("Sign in with Telegram", Authorization Code + PKCE S256).

**Prerequisites (one-time manual setup):**

1. Register your app on the Telegram developer portal and associate it with your existing bot.
2. Set the `redirect_uri` to `https://<ADMIN_WEB_PUBLIC_URL>/admin/auth/callback`.
3. Note `TELEGRAM_OIDC_CLIENT_ID` and `TELEGRAM_OIDC_CLIENT_SECRET`.

> **Note:** Telegram OIDC requires HTTPS on the callback URL. For local dev you can use a tunnel (ngrok/cloudflared) or configure `http://localhost:8080/admin/auth/callback` as a separate dev redirect_uri if Telegram permits it.

### New environment variables

| Variable | Default | Description |
|---|---|---|
| `ADMIN_WEB_ENABLED` | `true` | Set to `false` to disable the web panel entirely |
| `ADMIN_WEB_PORT` | `8080` | Port the admin panel listens on |
| `ADMIN_WEB_PUBLIC_URL` | `http://localhost:8080` | External HTTPS URL used for OIDC redirect_uri |
| `ADMIN_WEB_SECRET_KEY` | *(auto-generated)* | Cookie/CSRF signing key; auto-generated and persisted in `data/.secret_key` if not set |
| `ADMIN_SESSION_TTL_HOURS` | `168` | Session lifetime in hours (7 days) |
| `TELEGRAM_OIDC_CLIENT_ID` | *(required for login)* | Telegram OIDC client ID |
| `TELEGRAM_OIDC_CLIENT_SECRET` | *(required for login)* | Telegram OIDC client secret |
| `TELEGRAM_OIDC_DISCOVERY_URL` | `https://id.telegram.org/.well-known/openid-configuration` | OIDC discovery document URL |

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
