"""
Nemotron client — routes to local DGX Ollama, NVIDIA cloud, or OpenRouter.

Priority:
  1. DGX Ollama (set DGX_OLLAMA_URL=http://localhost:11434/v1 in .env)
  2. NVIDIA cloud API (NVIDIA_API_KEY)
  3. OpenRouter (OPENROUTER_API_KEY) — most reliable fallback
"""

import json
import logging
import re
import requests

from agent.config import (
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    DGX_OLLAMA_URL,
    NEMOTRON_MODEL_FAST,
    NEMOTRON_MODEL_MAIN,
    NEMOTRON_MODEL_FALLBACKS,
    NEMOTRON_TIMEOUT,
    NEMOTRON_MAX_TOKENS,
    NEMOTRON_TEMPERATURE,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL_MAIN,
    OPENROUTER_MODEL_FAST,
)

logger = logging.getLogger(__name__)

_SYSTEM_JSON = (
    "You are an expert music producer assistant. /no_think\n"
    "Respond with ONLY the requested format (JSON or plain text). "
    "No reasoning trace, no markdown fences unless asked."
)


def _is_local() -> bool:
    return bool(DGX_OLLAMA_URL)


def _model_chain(preferred: str | None) -> list[str]:
    chain = []
    if preferred:
        chain.append(preferred)
    for m in NEMOTRON_MODEL_FALLBACKS:
        if m not in chain:
            chain.append(m)
    return chain


def chat_completion(
    prompt: str,
    *,
    model: str | None = None,
    task: str = "main",
    max_tokens: int = NEMOTRON_MAX_TOKENS,
    temperature: float = NEMOTRON_TEMPERATURE,
    system_prompt: str = _SYSTEM_JSON,
) -> str:
    """
    Call local DGX Ollama → NVIDIA cloud → OpenRouter (in priority order).

    task:
      "main" → large Nemotron model
      "fast" → small/nano Nemotron model
    """
    if _is_local():
        try:
            return _local_chat(prompt, model=model, task=task,
                               max_tokens=max_tokens, temperature=temperature,
                               system_prompt=system_prompt)
        except Exception:
            pass  # fall through to cloud

    # Try NVIDIA cloud, then OpenRouter
    try:
        return _cloud_chat(prompt, model=model, task=task,
                           max_tokens=max_tokens, temperature=temperature,
                           system_prompt=system_prompt)
    except Exception as e:
        if OPENROUTER_API_KEY:
            logger.warning(f"NVIDIA cloud failed ({e}), trying OpenRouter...")
            return _openrouter_chat(prompt, task=task,
                                    max_tokens=max_tokens, temperature=temperature,
                                    system_prompt=system_prompt)
        raise


def _local_chat(
    prompt: str,
    *,
    model: str | None = None,
    task: str = "main",
    max_tokens: int = NEMOTRON_MAX_TOKENS,
    temperature: float = NEMOTRON_TEMPERATURE,
    system_prompt: str = _SYSTEM_JSON,
) -> str:
    preferred = model or (NEMOTRON_MODEL_FAST if task == "fast" else NEMOTRON_MODEL_MAIN)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    last_err: Exception | None = None

    for mid in _model_chain(preferred):
        payload = {
            "model": mid,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            "think": False,  # disable reasoning mode — we need JSON output
        }
        try:
            logger.info(f"Local Ollama → {mid} (task={task}) @ {DGX_OLLAMA_URL}")
            r = requests.post(
                f"{DGX_OLLAMA_URL}/chat/completions",
                json=payload,
                timeout=NEMOTRON_TIMEOUT,
            )
            if r.status_code == 404:
                logger.warning(f"Ollama model not found: {mid}, trying next")
                last_err = requests.HTTPError(f"404 for {mid}", response=r)
                continue
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content", "").strip()
            if not content:
                content = msg.get("reasoning", "").strip()
            content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
            return content.strip("```json").strip("```").strip()
        except requests.HTTPError as e:
            last_err = e
            if e.response is not None and e.response.status_code == 404:
                continue
            logger.warning(f"Local Ollama error ({mid}): {e}, falling back to cloud")
            return _cloud_chat(prompt, model=None, task=task,
                               max_tokens=max_tokens, temperature=temperature,
                               system_prompt=system_prompt)
        except Exception as e:
            logger.warning(f"Local Ollama unreachable: {e}, falling back to cloud")
            return _cloud_chat(prompt, model=None, task=task,
                               max_tokens=max_tokens, temperature=temperature,
                               system_prompt=system_prompt)

    raise last_err or RuntimeError("No local Ollama models available")


def _cloud_chat(
    prompt: str,
    *,
    model: str | None = None,
    task: str = "main",
    max_tokens: int = NEMOTRON_MAX_TOKENS,
    temperature: float = NEMOTRON_TEMPERATURE,
    system_prompt: str = _SYSTEM_JSON,
) -> str:
    if not NVIDIA_API_KEY:
        raise EnvironmentError("NVIDIA_API_KEY not set and DGX_OLLAMA_URL not configured")

    preferred = model or (NEMOTRON_MODEL_FAST if task == "fast" else NEMOTRON_MODEL_MAIN)
    # Ensure cloud model has correct prefix
    cloud_fallbacks = [
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nvidia-nemotron-nano-9b-v2",
    ]
    if not preferred.startswith("nvidia/"):
        preferred = cloud_fallbacks[0] if task != "fast" else cloud_fallbacks[1]

    chain = [preferred] + [m for m in cloud_fallbacks if m != preferred]
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    last_err: Exception | None = None

    for mid in chain:
        payload = {
            "model": mid,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
        }
        try:
            logger.info(f"NVIDIA cloud → {mid} (task={task})")
            r = requests.post(
                f"{NVIDIA_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=NEMOTRON_TIMEOUT,
            )
            if r.status_code == 404:
                last_err = requests.HTTPError(f"404 for {mid}", response=r)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
            return content.strip("```json").strip("```").strip()
        except requests.HTTPError as e:
            last_err = e
            if e.response is not None and e.response.status_code in (403, 404):
                logger.warning(f"NVIDIA cloud {e.response.status_code} for {mid}, trying next model")
                continue
            raise
        except Exception as e:
            last_err = e
            raise

    raise last_err or RuntimeError("No NVIDIA cloud models responded")


def _openrouter_chat(
    prompt: str,
    *,
    task: str = "main",
    max_tokens: int = NEMOTRON_MAX_TOKENS,
    temperature: float = NEMOTRON_TEMPERATURE,
    system_prompt: str = _SYSTEM_JSON,
) -> str:
    model = OPENROUTER_MODEL_MAIN if task != "fast" else OPENROUTER_MODEL_FAST
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/track-smith/aux",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    logger.info(f"OpenRouter → {model} (task={task})")
    r = requests.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=NEMOTRON_TIMEOUT,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
    return content.strip("```json").strip("```").strip()


def _repair_json_array(raw: str) -> list:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("options", [data])
        return data
    except json.JSONDecodeError:
        pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        return json.loads(raw[start: end + 1])
    raise json.JSONDecodeError("No JSON array found", raw, 0)


def chat_json_array(prompt: str, *, task: str = "main", **kwargs) -> list:
    raw = chat_completion(prompt, task=task, **kwargs)
    data = _repair_json_array(raw)
    if isinstance(data, dict):
        data = data.get("options", [data])
    return data
