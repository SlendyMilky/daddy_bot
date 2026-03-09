# Telegram Streaming Skill Notes

## Context

Telegram supports native draft streaming through `sendMessageDraft` using:
- `chat_id`
- `draft_id`
- `text`

This allows animated progressive updates tied to the same draft ID.

## Why not enabled now

The current implementation intentionally uses the stable fallback method:
1. Send a placeholder message.
2. Edit the message periodically as tokens arrive.
3. Finalize with the complete response.

Additionally, we send `typing` chat action while generation is running to improve UX.

## Future implementation idea

When enabling native draft streaming:
- Keep `draft_id` stable for one generation.
- Push partial text chunks with `sendMessageDraft`.
- Send final text as last draft update.
- Keep fallback to edit-based flow when API support is unavailable.
