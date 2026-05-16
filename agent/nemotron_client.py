"""NVIDIA Nemotron API client — hackathon-compliant model selection."""

import json
import logging
import re
import requests

from agent.config import (
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NEMOTRON_MODEL_FAST,
    NEMOTRON_MODEL_MAIN,
    NEMOTRON_MODEL_FALLBACKS,
    NEMOTRON_TIMEOUT,
    NEMOTRON_MAX_TOKENS,
    NEMOTRON_TEMPERATURE,
)

logger = logging.getLogger(__name__)

# Reasoning OFF for structured JSON (see Nemotron docs: /no_think in system prompt)
_SYSTEM_JSON = (
    "You are an expert music producer assistant. /no_think\n"
    "Respond with ONLY the requested format (JSON or plain text). "
    "No reasoning trace, no markdown fences unless asked."
)


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
    Call NVIDIA integrate.api chat/completions using Nemotron models only.

    task:
      - "main" → llama-3.3-nemotron-super-49b-v1.5 (fill, vibe, mix)
      - "fast" → nvidia-nemotron-nano-9b-v2 (suggest, quick text)
    """
    if not NVIDIA_API_KEY:
        raise EnvironmentError("NVIDIA_API_KEY is not set")

    preferred = model or (
        NEMOTRON_MODEL_FAST if task == "fast" else NEMOTRON_MODEL_MAIN
    )
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
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
            "top_p": 0.95,
        }
        try:
            logger.info(f"Nemotron API → {mid} (task={task})")
            response = requests.post(
                f"{NVIDIA_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=NEMOTRON_TIMEOUT,
            )
            if response.status_code == 404:
                logger.warning(f"Nemotron model not found: {mid}")
                last_err = requests.HTTPError(f"404 for {mid}", response=response)
                continue
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            # Strip Nemotron reasoning trace if present despite /no_think
            content = re.sub(
                r"<think>.*?</think>\s*",
                "",
                content,
                flags=re.DOTALL,
            )
            return content.strip("```json").strip("```").strip()
        except requests.HTTPError as e:
            last_err = e
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        except Exception as e:
            last_err = e
            raise

    raise last_err or RuntimeError(
        "No Nemotron models available. Check NVIDIA_API_KEY and model names in .env"
    )


def chat_json_array(prompt: str, *, task: str = "main", **kwargs) -> list:
    raw = chat_completion(prompt, task=task, **kwargs)
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("options", [data])
    return data
