from __future__ import annotations

import logging
from typing import Iterable

from ...config import settings
from ...core.llm import LLMProvider, get_llm_provider
from .skill_loader import with_director_skill

logger = logging.getLogger("director_studio.llm_plan")

_VISION_MARKERS = (
    "vl",
    "vision",
    "llava",
    "minicpm-v",
    "moondream",
    "pixtral",
    "qwen2.5vl",
    "qwen2-vl",
    "qwen2vl",
    "qwen3.8-uncensored",
    "muse-glimmer",
)


def looks_like_vision_model(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _VISION_MARKERS)


class DirectorLLMPlanProvider:
    """Director planning adapter backed by the configured active LLM provider."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self.provider = provider or get_llm_provider()
        self._fixed_model = model
        self.client = self.provider.client

    @property
    def model(self) -> str:
        if self._fixed_model:
            return self._fixed_model
        return str(self.provider.model_status().get("model") or "").strip()

    async def complete(
        self,
        system: str,
        user: str,
        *,
        guides: Iterable[str] = (),
    ) -> str:
        prompt = with_director_skill(f"{system}\n\n{user}", guides=guides)
        return await self.client.generate(
            self.model,
            prompt,
            format="json",
            think=False,
        )

    async def vision_model(self) -> str:
        """Model that can inspect images. Plan models like qwen3:32b cannot."""
        configured = (settings.director_vision_model or "").strip()
        if configured:
            return configured
        current = self.model
        if looks_like_vision_model(current):
            return current
        names: list[str] = []
        list_models = getattr(self.client, "list_models", None)
        if callable(list_models):
            try:
                names = list(await list_models())
            except Exception:
                logger.warning("could not list models to pick a vision fallback", exc_info=True)
        for name in names:
            if looks_like_vision_model(str(name)):
                logger.info(
                    "Director plan model %s has no vision; using %s for image inspection",
                    current,
                    name,
                )
                return str(name)
        raise ValueError(
            f"Material review needs a vision model to inspect Pictures. "
            f"Director is using {current or '(none)'}, which cannot accept images. "
            "Pull a VL model (for example `ollama pull qwen2.5vl:7b`) or set "
            "DS_DIRECTOR_VISION_MODEL."
        )

    async def complete_with_images(
        self,
        system: str,
        user: str,
        *,
        images: list[str],
        guides: Iterable[str] = (),
    ) -> str:
        prompt = with_director_skill(f"{system}\n\n{user}", guides=guides)
        model = await self.vision_model()
        return await self.client.chat(
            model,
            prompt,
            images=images,
            require_vision=True,
        )
