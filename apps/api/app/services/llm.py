"""模型客户端：OpenAI 兼容协议，支持流式；未配置密钥时明确降级而不假装可用。"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from ..core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    """未配置 LLM 密钥。调用方据此切换到抽取式回答。"""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_base_url)

    def _payload(self, messages: list[dict[str, str]], stream: bool, model: str | None) -> dict:
        return {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": 0.15,
            "stream": stream,
        }

    async def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        if not self.available:
            raise LLMNotConfigured("未配置 LLM_API_KEY")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url, headers=headers, json=self._payload(messages, False, model)
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream(
        self, messages: list[dict[str, str]], model: str | None = None
    ) -> AsyncIterator[str]:
        if not self.available:
            raise LLMNotConfigured("未配置 LLM_API_KEY")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", url, headers=headers, json=self._payload(messages, True, model)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    piece = delta.get("content")
                    if piece:
                        yield piece
