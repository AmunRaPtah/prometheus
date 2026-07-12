"""Local LLM client — llama-swap's OpenAI-compatible endpoint (small on-box models).

llama-swap (http://127.0.0.1:8080 by default) loads one of a small set of local GGUF
models on demand and unloads it after an idle TTL, exposing a standard OpenAI
`/v1/chat/completions` surface. This is a different shape from `llm.py` (DeepSeek's
Anthropic-Messages-shaped API: `x-api-key`, `/v1/messages`, `content` blocks) — hence a
separate client rather than a mode switch on `llm.py`.

Unlike `net.py`'s resilient client (built to protect *shared, rate-limited, external*
APIs across many connectors), a local single-user server's failure mode is "not
running" or "still loading a model," not "429 me" — so this client has no rate
limiter or circuit breaker, just a generous timeout (a cold model swap can take tens
of seconds) and a short manual retry loop, mirroring `llm.py`'s own retry shape.

`available()` lets callers (e.g. `entities.py`) degrade gracefully when llama-swap
isn't reachable — notably true on every GitHub Actions run, since the runner has no
route to this box's `127.0.0.1:8080`. This client is only ever exercised locally.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "granite-4.0-h-1b"  # llama-swap's light "classify/tag/scope/JSON" tier


class LocalLLMUnavailable(RuntimeError):
    """Raised when the local llama-swap endpoint can't be reached."""


def config() -> dict:
    return {
        "base": os.environ.get("PROMETHEUS_LOCAL_LLM_URL", DEFAULT_BASE),
        "model": os.environ.get("PROMETHEUS_LOCAL_LLM_MODEL", DEFAULT_MODEL),
    }


def available(*, timeout: float = 3.0) -> bool:
    """Cheap health check — GET /models. False on any error (not just connection-refused)."""
    cfg = config()
    try:
        req = urllib.request.Request(f"{cfg['base']}/models")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _build(prompt: str, system: str | None, model: str, max_tokens: int,
           temperature: float) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}


def _parse(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "").strip()


def complete(prompt: str, *, system: str | None = None, model: str | None = None,
             max_tokens: int = 800, temperature: float = 0.1, retries: int = 2,
             timeout: float = 200.0) -> str:
    """Send one chat completion and return the model's text.

    `timeout` defaults high enough to cover a cold model load / TTL swap in
    llama-swap (up to its `healthCheckTimeout`), not just steady-state inference.
    """
    cfg = config()
    body = json.dumps(_build(prompt, system, model or cfg["model"],
                             max_tokens, temperature)).encode()
    req = urllib.request.Request(
        f"{cfg['base']}/chat/completions", data=body,
        headers={"content-type": "application/json"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _parse(json.loads(r.read()))
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt + 1 < retries:
                time.sleep(2.0 * (attempt + 1))
    raise LocalLLMUnavailable(
        f"local LLM request failed after {retries} tries ({cfg['base']})") from last
