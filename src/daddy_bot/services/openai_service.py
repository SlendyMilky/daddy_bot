from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIService:
    def __init__(self, api_key: str | None, model: str = "gpt-4.1-mini"):
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key) if api_key else None

    @staticmethod
    def fallback_start_message() -> str:
        return "Bienvenue chez Daddy. Pose ta question, Papa gere la suite."

    async def stream_start_message(self) -> AsyncIterator[str]:
        if self._client is None:
            yield self.fallback_start_message()
            return

        try:
            async with self._client.responses.stream(
                model=self.model,
                input=(
                    "Ecris une TRES COURTE description de bienvenue expliquant que tu es Daddy, "
                    "le bot telegram de @Slendy_Milky dans sa nouvelle forme. Ton de Papa."
                ),
                temperature=1.0,
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", "") == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            yield delta
                await stream.get_final_response()
        except Exception:
            logger.exception("OpenAI start streaming failed")
            yield self.fallback_start_message()

    async def generate_start_message(self) -> str:
        if self._client is None:
            return self.fallback_start_message()

        try:
            response = await self._client.responses.create(
                model=self.model,
                input=(
                    "Ecris une TRES COURTE description de bienvenue expliquant que tu es Daddy, "
                    "le bot telegram de @Slendy_Milky dans sa nouvelle forme. Ton de Papa."
                ),
                temperature=1.0,
            )
            text = response.output_text.strip()
            if text:
                return text
        except Exception:
            logger.exception("OpenAI start generation failed")

        return self.fallback_start_message()
