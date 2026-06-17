"""Async wrapper for Ollama's REST API."""
import httpx
import json
import os
from typing import AsyncGenerator

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

async def check_connection() -> bool:
    """Check if Ollama is running."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    """List available Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


async def generate(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    format: str = None,
) -> AsyncGenerator[str, None]:
    """Stream a generation response from Ollama, yielding text chunks."""
    payload = {
        "model": model,
        "prompt": user_prompt,
        "system": system_prompt,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": 8192,
        },
    }
    if format == "json":
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done", False):
                        return
                except json.JSONDecodeError:
                    continue


async def generate_full(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
) -> str:
    """Run a full (non-streaming) generation and return the complete text."""
    full_text = []
    async for chunk in generate(model, system_prompt, user_prompt, temperature):
        full_text.append(chunk)
    return "".join(full_text)
