"""Async DeepSeek API client with multi-key round-robin rotation.

OpenAI-compatible interface — same generate() / generate_full() signature as gemini_client.py.
Used as a transparent fallback when all Gemini keys/models are exhausted.

Free tier: 5M tokens per account, no hard rate limits, best-effort throttling.
"""
import httpx
import json
import asyncio
import logging
import os
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ── API Key Pool (loaded from environment variables) ─────────────────────────
# Set DEEPSEEK_API_KEY_1, DEEPSEEK_API_KEY_2, DEEPSEEK_API_KEY_3 in your .env file.
DEEPSEEK_KEYS = [v for v in [
    os.getenv("DEEPSEEK_API_KEY_1", ""),
    os.getenv("DEEPSEEK_API_KEY_2", ""),
    os.getenv("DEEPSEEK_API_KEY_3", ""),
] if v]

if not DEEPSEEK_KEYS:
    logger.warning("No DeepSeek API keys configured! Set DEEPSEEK_API_KEY_* env vars.")

# ── Model priority (best to fastest) ─────────────────────────────────────────
# deepseek-chat   = DeepSeek V3  — fast, general purpose, best for our pipeline
# deepseek-reasoner = DeepSeek R1 — slower, chain-of-thought, higher token cost
DEEPSEEK_MODELS = [
    "deepseek-chat",       # Primary: V3, fast & cheap
    "deepseek-reasoner",   # Fallback: R1, more thorough but uses more tokens
]

PRIMARY_MODEL = DEEPSEEK_MODELS[0]

DEEPSEEK_BASE = "https://api.deepseek.com/v1"

# ── Round-robin key counter ────────────────────────────────────────────────
_key_index = 0
_key_lock = asyncio.Lock()

# ── Concurrency limiter: max parallel = number of keys ────────────────────
DEEPSEEK_SEMAPHORE = asyncio.Semaphore(len(DEEPSEEK_KEYS))


async def _next_key() -> str:
    """Get the next API key in round-robin order."""
    global _key_index
    async with _key_lock:
        key = DEEPSEEK_KEYS[_key_index % len(DEEPSEEK_KEYS)]
        _key_index += 1
        return key


async def check_connection() -> bool:
    """Check if DeepSeek API is reachable with at least one key."""
    try:
        key = DEEPSEEK_KEYS[0]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{DEEPSEEK_BASE}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            return resp.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    """List available DeepSeek models."""
    return DEEPSEEK_MODELS


async def generate(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    format: str = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a generation response from DeepSeek API, yielding text chunks.

    Mirrors gemini_client.generate() interface exactly.
    - Tries requested model first, then falls back to remaining models.
    - For each model, cycles through all API keys.
    """
    # Map Gemini model names to DeepSeek equivalents if passed in
    if model not in DEEPSEEK_MODELS:
        target = PRIMARY_MODEL
    else:
        target = model

    models_to_try = [target] + [m for m in DEEPSEEK_MODELS if m != target]

    # Build message payload (OpenAI format)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error = None

    for target_model in models_to_try:
        for key_offset in range(len(DEEPSEEK_KEYS)):
            api_key = await _next_key()

            body = {
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 8192,
                "stream": True,
            }

            # JSON mode: ask DeepSeek to return JSON object
            if format == "json":
                body["response_format"] = {"type": "json_object"}

            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(300.0, connect=15.0)
                ) as client:
                    async with client.stream(
                        "POST",
                        f"{DEEPSEEK_BASE}/chat/completions",
                        json=body,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        if response.status_code == 429:
                            error_body = await response.aread()
                            logger.warning(
                                f"DeepSeek rate limit hit ({target_model}, key ...{api_key[-6:]}): "
                                f"{error_body.decode('utf-8', errors='ignore')[:200]}"
                            )
                            last_error = f"Rate limit (429) on {target_model}"
                            await asyncio.sleep(3)
                            continue  # Try next key

                        if response.status_code == 402:
                            logger.warning(
                                f"DeepSeek insufficient balance (key ...{api_key[-6:]}). Skipping."
                            )
                            last_error = "Insufficient balance (402)"
                            continue  # Try next key

                        if response.status_code != 200:
                            error_body = await response.aread()
                            error_msg = error_body.decode("utf-8", errors="ignore")
                            logger.warning(
                                f"DeepSeek {target_model} (key ...{api_key[-6:]}) "
                                f"HTTP {response.status_code}: {error_msg[:200]}"
                            )
                            last_error = f"HTTP {response.status_code}: {error_msg[:200]}"
                            continue

                        # Stream SSE lines (OpenAI format)
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or line == "data: [DONE]":
                                continue
                            if line.startswith("data: "):
                                json_str = line[6:]
                            else:
                                continue

                            try:
                                chunk = json.loads(json_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    text = delta.get("content", "")
                                    if text:
                                        yield text
                            except json.JSONDecodeError:
                                continue

                        return  # Success

            except Exception as e:
                logger.warning(
                    f"DeepSeek {target_model} (key ...{api_key[-6:]}) stream failed: {e}"
                )
                last_error = str(e)
                continue

    logger.error(f"All DeepSeek key×model combos failed. Last error: {last_error}")
    yield f"[DEEPSEEK ERROR: All models and keys exhausted. {last_error}]"


async def generate_full(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    format: str = None,
) -> str:
    """Run a full (non-streaming) generation with concurrency throttling.

    Acquires the global semaphore so at most len(DEEPSEEK_KEYS) calls run in parallel.
    """
    async with DEEPSEEK_SEMAPHORE:
        full_text = []
        async for chunk in generate(model, system_prompt, user_prompt, temperature, format):
            full_text.append(chunk)
        return "".join(full_text)
