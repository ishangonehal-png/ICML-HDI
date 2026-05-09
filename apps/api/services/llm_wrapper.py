"""
_llm_wrapper.py
===============
Thin provider-agnostic wrapper around chat-completion style calls.

Dispatches on model name prefix:
  - "gemini*"  -> Google Generative AI (google-genai)
  - otherwise  -> OpenAI chat.completions

Returns the assistant message content string. Meant to be a drop-in replacement
for `client.chat.completions.create(...).choices[0].message.content`.

Env vars:
  OPENAI_API_KEY   - required for OpenAI models
  GEMINI_API_KEY   - required for gemini-* models
"""
from __future__ import annotations

import os
from typing import Any


def chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    response_format: dict | None = None,
    max_tokens: int | None = None,
) -> str:
    if model.startswith("gemini"):
        return _gemini_chat(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
        )
    return _openai_chat(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
    )


def _openai_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    response_format: dict | None,
    max_tokens: int | None,
) -> str:
    from openai import OpenAI
    client = OpenAI()
    kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
    if response_format is not None:
        kwargs["response_format"] = response_format
    # GPT-5 family uses max_completion_tokens; older uses max_tokens.
    # We only pass the budget if explicitly requested.
    if max_tokens is not None:
        if model.startswith("gpt-5"):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _gemini_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    response_format: dict | None,
    max_tokens: int | None,
) -> str:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
    import time as _time

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY env var not set")
    # Per-request timeout (ms) so a dead TCP socket surfaces as an exception
    # rather than hanging the pipeline forever. Value is intentionally generous
    # to accommodate long judge prompts.
    http_options = types.HttpOptions(timeout=120_000)
    client = genai.Client(api_key=api_key, http_options=http_options)

    # Collapse OpenAI-style messages into Gemini's (system_instruction, contents)
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    user_parts = [m["content"] for m in messages if m.get("role") in ("user", "assistant")]
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    contents = "\n\n".join(user_parts) if user_parts else ""

    cfg_kwargs: dict[str, Any] = {"temperature": temperature}
    if system_instruction:
        cfg_kwargs["system_instruction"] = system_instruction
    if response_format and response_format.get("type") == "json_object":
        cfg_kwargs["response_mime_type"] = "application/json"
    if max_tokens is not None:
        cfg_kwargs["max_output_tokens"] = max_tokens
    config = types.GenerateContentConfig(**cfg_kwargs)

    # Retry with exponential backoff on transient server errors (503/429).
    # The built-in SDK retry already fires on ServerError; we extend it with
    # our own outer loop so long runs survive multi-minute overload windows.
    max_attempts = 6
    backoff = 5.0  # seconds; doubles each attempt up to ~2.5 min total
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
            return resp.text or ""
        except genai_errors.ServerError as e:
            last_err = e
            code = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status_code", None)
            if code in (503, 429, 500) and attempt < max_attempts - 1:
                _time.sleep(backoff)
                backoff *= 2
                continue
            raise
        except genai_errors.ClientError as e:
            # 429 sometimes surfaces as ClientError depending on SDK version.
            last_err = e
            code = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status_code", None)
            if code == 429 and attempt < max_attempts - 1:
                _time.sleep(backoff)
                backoff *= 2
                continue
            raise
        except Exception as e:
            # Network-level timeout / socket error from the underlying HTTP client.
            # Retry with backoff; the HttpOptions(timeout=...) above turns a dead
            # socket into an exception instead of a forever-hang.
            msg = str(e).lower()
            if ("timeout" in msg or "timed out" in msg or "read timed out" in msg
                    or "remotedisconnected" in msg or "connection" in msg) and attempt < max_attempts - 1:
                last_err = e
                _time.sleep(backoff)
                backoff *= 2
                continue
            raise
    if last_err is not None:
        raise last_err
    return ""
