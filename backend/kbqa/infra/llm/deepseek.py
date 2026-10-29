"""DeepSeek（OpenAI 兼容）客户端：超时、重试、错误分类（见 03_核心机制/03 §2）。"""

from __future__ import annotations

import asyncio
import time

import httpx

from kbqa.core.generation.types import LLMUnavailable, RawCompletion

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class DeepSeekClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat", default_timeout: int = 45,
                 max_retry: int = 1, backoff: float = 1.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.model = model
        self.default_timeout = default_timeout
        self.max_retry = max_retry
        self.backoff = backoff
        self.api_key = (api_key or "").strip()
        headers = {"Content-Type": "application/json"}
        # 关键：key 为空时绝不能带 "Authorization: Bearer "（尾随空格会被 httpx 判为非法头，
        # 直接抛 LocalProtocolError，把"模型不可用"变成 500 系统错误）
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=default_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, messages: list[dict], *, temperature: float = 0.1,
                       max_tokens: int = 1024, timeout: int | None = None,
                       json_mode: bool = True) -> RawCompletion:
        if not self.api_key:
            raise LLMUnavailable("E-3003", "未配置 DEEPSEEK_API_KEY")

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error = "unknown"
        for attempt in range(self.max_retry + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._client.post(
                    "/chat/completions", json=payload,
                    timeout=timeout or self.default_timeout)
                if resp.status_code in RETRYABLE_STATUS:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < self.max_retry:
                        await asyncio.sleep(self.backoff * (2 if resp.status_code == 429 else 1))
                        continue
                    raise LLMUnavailable("E-3003", last_error)
                resp.raise_for_status()
                body = resp.json()
                usage = body.get("usage") or {}
                return RawCompletion(
                    text=body["choices"][0]["message"]["content"],
                    model=body.get("model", self.model),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retry:
                    await asyncio.sleep(self.backoff)
                    continue
                raise LLMUnavailable("E-3002", last_error) from exc
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                last_error = f"HTTP {code}: {exc.response.text[:200]}"
                # 401/400 不重试：重试也不会好
                raise LLMUnavailable("E-3003", last_error) from exc

        raise LLMUnavailable("E-3003", last_error)
