"""Unified Multi-Provider LLM Client — Gemini + DeepSeek interleaved.

7 API keys across 2 providers, round-robin interleaved for maximum throughput.
Zero sleep on 429 — immediately skips to the next slot.
Semaphore = 7 so all slots can run in parallel simultaneously.

Slot order (interleaved, best-available-first strategy):
  0: DeepSeek-1  → deepseek-chat     (V3 — fast, cheap, very capable)
  1: Gemini-1    → gemini-2.5-flash  (very strong)
  2: DeepSeek-2  → deepseek-chat
  3: Gemini-2    → gemini-2.5-flash
  4: DeepSeek-3  → deepseek-chat
  5: Gemini-3    → gemini-2.5-flash
  6: Gemini-4    → gemini-2.5-flash

Model fallback per provider (tried if primary is overloaded):
  DeepSeek: deepseek-chat → deepseek-reasoner
  Gemini:   gemini-2.5-flash → gemini-3-flash-preview → gemini-2.5-flash-lite
"""
import httpx
import json
import asyncio
import logging
import os
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ── Unified Slot Pool (interleaved DeepSeek + Gemini) ─────────────────────────
# Keys are loaded from environment variables for security.
# Set DEEPSEEK_API_KEY_1..3 and GEMINI_API_KEY_1..4 in your .env file.
SLOTS = []
for _i in range(1, 4):
    _k = os.getenv(f"DEEPSEEK_API_KEY_{_i}", "")
    if _k:
        SLOTS.append({"provider": "deepseek", "key": _k})
for _i in range(1, 5):
    _k = os.getenv(f"GEMINI_API_KEY_{_i}", "")
    if _k:
        SLOTS.append({"provider": "gemini", "key": _k})

if not SLOTS:
    logger.warning("No API keys configured! Set DEEPSEEK_API_KEY_* and/or GEMINI_API_KEY_* env vars.")

# ── Model fallback chains per provider ────────────────────────────────────────
DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"]
GEMINI_MODELS   = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash-lite"]

# ── For list_models() / external display ──────────────────────────────────────
MODELS_BY_POWER = ["deepseek-chat"] + GEMINI_MODELS + ["deepseek-reasoner"]
PRIMARY_MODEL   = "deepseek-chat"

# ── API endpoints ─────────────────────────────────────────────────────────────
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
GEMINI_BASE   = "https://generativelanguage.googleapis.com/v1beta"

# ── Round-robin slot counter ──────────────────────────────────────────────────────────────
_slot_index = 0
_slot_lock  = asyncio.Lock()

# ── Semaphore: all 7 slots can run simultaneously ──────────────────────────────────
API_SEMAPHORE = asyncio.Semaphore(len(SLOTS))


async def check_connection() -> bool:
    """Check if any provider is reachable."""
    # Try Gemini first
    try:
        gemini_slot = next(s for s in SLOTS if s["provider"] == "gemini")
        url = f"{GEMINI_BASE}/models?key={gemini_slot['key']}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            if (await client.get(url)).status_code == 200:
                return True
    except Exception:
        pass
    # Try DeepSeek
    try:
        ds_slot = next(s for s in SLOTS if s["provider"] == "deepseek")
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{DEEPSEEK_BASE}/models",
                headers={"Authorization": f"Bearer {ds_slot['key']}"},
            )
            return resp.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    """List all available models across providers."""
    return MODELS_BY_POWER


# ── Internal: call DeepSeek (streaming) ───────────────────────────────────────
async def _stream_deepseek(
    key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    json_mode: bool,
) -> AsyncGenerator[str, None]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 8192,
        "stream": True,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=12.0)) as client:
        async with client.stream(
            "POST",
            f"{DEEPSEEK_BASE}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        ) as resp:
            if resp.status_code in (429, 402):
                await resp.aread()
                raise _RateLimitError(resp.status_code)
            if resp.status_code != 200:
                body_txt = (await resp.aread()).decode("utf-8", errors="ignore")
                raise _APIError(resp.status_code, body_txt[:200])

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        text = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if text:
                            yield text
                    except json.JSONDecodeError:
                        continue


# ── Internal: call Gemini (streaming) ─────────────────────────────────────────
async def _stream_gemini(
    key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    json_mode: bool,
) -> AsyncGenerator[str, None]:
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192},
    }
    if json_mode:
        body["generationConfig"]["response_mime_type"] = "application/json"

    url = f"{GEMINI_BASE}/models/{model}:streamGenerateContent?alt=sse&key={key}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=12.0)) as client:
        async with client.stream(
            "POST", url,
            json=body,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status_code == 429:
                await resp.aread()
                raise _RateLimitError(429)
            if resp.status_code != 200:
                body_txt = (await resp.aread()).decode("utf-8", errors="ignore")
                raise _APIError(resp.status_code, body_txt[:200])

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                    for cand in chunk.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            text = part.get("text", "")
                            if text:
                                yield text
                except json.JSONDecodeError:
                    continue


# ── Sentinel exceptions ────────────────────────────────────────────────────────
class _RateLimitError(Exception):
    def __init__(self, code): self.code = code
class _APIError(Exception):
    def __init__(self, code, msg): self.code = code; self.msg = msg


# ── Public API ─────────────────────────────────────────────────────────────────
async def generate(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    format: str = None,
) -> AsyncGenerator[str, None]:
    """
    Stream LLM generation, yielding text chunks.

    Strategy:
      1. Try all 7 slots in round-robin with their primary model.
      2. If all 7 slots return 429, try fallback models across all slots.
      3. No sleep between slot attempts — instant skip on rate-limit.
    """
    json_mode = (format == "json")

    # Build (slot, model) attempt list:
    # Pass 1: all 7 slots with each provider's PRIMARY model
    # Pass 2: all 7 slots with each provider's first FALLBACK model
    # Pass 3: all 7 slots with each provider's second FALLBACK model (if exists)
    attempts: list[tuple[dict, str]] = []
    max_fallback_depth = max(len(DEEPSEEK_MODELS), len(GEMINI_MODELS))
    for depth in range(max_fallback_depth):
        for slot in SLOTS:
            models_list = DEEPSEEK_MODELS if slot["provider"] == "deepseek" else GEMINI_MODELS
            if depth < len(models_list):
                attempts.append((slot, models_list[depth]))

    # Atomically claim a starting position in the rotation so every
    # parallel generate() call begins from a different slot.
    async with _slot_lock:
        global _slot_index
        start = _slot_index % len(SLOTS)
        _slot_index += 1

    # Reorder pass-1 attempts to start from this call's slot
    p1 = attempts[:len(SLOTS)]
    p1 = p1[start:] + p1[:start]
    rest = attempts[len(SLOTS):]
    ordered_attempts = p1 + rest

    last_error = "No attempts made"
    for slot, try_model in ordered_attempts:
        key      = slot["key"]
        provider = slot["provider"]
        try:
            streamer = (
                _stream_deepseek(key, try_model, system_prompt, user_prompt, temperature, json_mode)
                if provider == "deepseek"
                else _stream_gemini(key, try_model, system_prompt, user_prompt, temperature, json_mode)
            )
            got_any = False
            async for chunk in streamer:
                got_any = True
                yield chunk
            if got_any:
                return  # ✅ Success

        except _RateLimitError as e:
            logger.debug(f"[{provider}] key ...{key[-6:]} model={try_model} → {e.code}, skipping")
            last_error = f"Rate-limit {e.code} on {provider}/{try_model}"
            continue  # ← zero sleep, instant next slot

        except _APIError as e:
            logger.warning(f"[{provider}] key ...{key[-6:]} model={try_model} → HTTP {e.code}: {e.msg}")
            last_error = f"HTTP {e.code} on {provider}/{try_model}"
            continue

        except Exception as e:
            logger.warning(f"[{provider}] key ...{key[-6:]} model={try_model} stream failed: {e}")
            last_error = str(e)
            continue

    logger.error(f"All {len(ordered_attempts)} slot×model attempts failed. Last: {last_error}")
    yield f"[LLM ERROR: All providers exhausted. {last_error}]"


async def generate_full(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    format: str = None,
) -> str:
    """Non-streaming generation with semaphore throttling.

    Acquires one of the 7 semaphore slots so at most 7 calls run simultaneously.
    """
    async with API_SEMAPHORE:
        chunks: list[str] = []
        async for chunk in generate(model, system_prompt, user_prompt, temperature, format):
            chunks.append(chunk)
        return "".join(chunks)
