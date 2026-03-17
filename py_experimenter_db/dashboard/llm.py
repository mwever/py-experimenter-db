"""OpenAI-compatible LLM client (works with OpenAI, Ollama, LM Studio, vLLM, …)."""

from __future__ import annotations

import httpx


async def chat_completion(
    messages: list[dict],
    url: str,
    token: str = "",
    model: str = "gpt-4o",
    timeout: float = 120.0,
) -> str:
    """Send a messages list to an OpenAI-compatible endpoint and return the reply."""
    if not url:
        raise ValueError(
            "LLM URL is not configured. Add it in the Configuration page (LLM Connector section)."
        )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoint = url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]
