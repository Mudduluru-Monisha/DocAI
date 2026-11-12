"""Gemini wrapper: rate-limit pacing, retries with backoff, JSON parsing, streaming."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Iterator

from . import config


class LLMError(Exception):
    pass


_lock = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    """Keep calls at or below GEMINI_RPM so the free tier doesn't reject us."""
    global _last_call
    gap = 60.0 / max(config.RPM, 1)
    with _lock:
        wait = _last_call + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def parse_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(t[a : b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Model did not return valid JSON")


def _friendly(msg: str) -> str:
    low = msg.lower()
    if "api key not valid" in low or "api_key_invalid" in low or "permission_denied" in low:
        return "Gemini rejected the API key. Check it at aistudio.google.com/apikey."
    if "429" in msg or "resource_exhausted" in low:
        return ("Gemini's free-tier rate or daily quota was reached. Wait a minute and resume, "
                "lower GEMINI_RPM, or try again after the daily reset (midnight Pacific).")
    if "not_found" in low or "no longer available" in low or ("not found" in low and "model" in low):
        return ("Google no longer serves the configured Gemini model. Change the model name in the sidebar "
                "(Models) or in .env (GEMINI_FAST_MODEL / GEMINI_SMART_MODEL). Current free option: gemini-3.5-flash-lite.")
    return msg[:400]


_TRANSIENT = ("429", "RESOURCE_EXHAUSTED", "500", "502", "503", "504", "UNAVAILABLE", "DEADLINE", "overloaded")


def _retry_delay(msg: str, default: float) -> float:
    m = re.search(r"retry(?:delay)?\W+(?:in\s+)?['\"]?(\d+(?:\.\d+)?)\s*s", msg, re.I)
    return min(float(m.group(1)) + 1, 90.0) if m else default


class LLM:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise LLMError("No Gemini API key. Add GEMINI_API_KEY to .env or paste it in the sidebar.")
        from google import genai
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=self.api_key)

    def _cfg(self, model, system, json_mode, temperature, max_tokens):
        kw = dict(temperature=temperature, max_output_tokens=max_tokens)
        if system:
            kw["system_instruction"] = system
        if json_mode:
            kw["response_mime_type"] = "application/json"
        if "2.5" in model and "flash" in model:
            kw["thinking_config"] = self._types.ThinkingConfig(thinking_budget=0)
        return self._types.GenerateContentConfig(**kw)

    def _call(self, fn):
        delay = 6.0
        for attempt in range(6):
            _throttle()
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if attempt == 5 or not any(s in msg for s in _TRANSIENT):
                    raise LLMError(_friendly(msg)) from e
                time.sleep(_retry_delay(msg, delay))
                delay = min(delay * 2, 60.0)

    def generate(self, prompt, *, system=None, model=None, json_mode=False, temperature=0.2, max_tokens=4096) -> str:
        model = model or config.FAST_MODEL
        cfg = self._cfg(model, system, json_mode, temperature, max_tokens)
        resp = self._call(lambda: self.client.models.generate_content(model=model, contents=prompt, config=cfg))
        text = resp.text or ""
        if not text.strip():
            raise LLMError("Gemini returned an empty response (it may have been blocked by a safety filter).")
        return text

    def generate_json(self, prompt, *, system=None, model=None, temperature=0.1, max_tokens=8192):
        for attempt in range(2):
            p = prompt if attempt == 0 else prompt + "\n\nIMPORTANT: reply with valid JSON only, no prose."
            raw = self.generate(p, system=system, model=model, json_mode=True,
                                temperature=temperature, max_tokens=max_tokens)
            try:
                return parse_json(raw)
            except ValueError:
                continue
        raise LLMError("Could not parse the model's JSON output.")

    def stream(self, prompt, *, system=None, model=None, temperature=0.3, max_tokens=4096) -> Iterator[str]:
        model = model or config.SMART_MODEL
        cfg = self._cfg(model, system, False, temperature, max_tokens)
        delay = 6.0
        for attempt in range(4):
            _throttle()
            started = False
            try:
                for chunk in self.client.models.generate_content_stream(model=model, contents=prompt, config=cfg):
                    if chunk.text:
                        started = True
                        yield chunk.text
                return
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if started or attempt == 3 or not any(s in msg for s in _TRANSIENT):
                    raise LLMError(_friendly(msg)) from e
                time.sleep(_retry_delay(msg, delay))
                delay = min(delay * 2, 60.0)
