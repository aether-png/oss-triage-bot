"""
Multi-provider LLM client with fallback chain.

Tries providers in order until one succeeds. Every provider here has a free
tier. If a key isn't set in the environment, that provider is skipped
silently. If ALL providers fail or no keys are set, the caller should fall
back to pure heuristics (see filter_issues.py).

Providers (in try-order): Groq -> Cerebras -> Gemini -> OpenRouter
"""

import json
import os
import urllib.request
import urllib.error
import time


_GROQ_MIN_INTERVAL = 2.1
_last_groq_request = 0.0
_groq_requests = 0
_GROQ_MAX_REQUESTS_PER_RUN = 25

def _wait_for_groq_slot():
    global _last_groq_request
    now = time.monotonic()
    delay = _last_groq_request + _GROQ_MIN_INTERVAL - now
    if delay > 0:
        time.sleep(delay)
    _last_groq_request = time.monotonic()

def _post_json(url, headers, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"User-Agent": "oss-triage-bot/1.0", **headers}
    req = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e


def _call_groq(prompt):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    global _groq_requests
    if _groq_requests >= GROQ_MAX_REQUESTS_PER_RUN:
        return None
    _wait_for_groq_slot()
    _groq_requests += 1
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 200,
    }
    out = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body,
    )
    return out["choices"][0]["message"]["content"]


def _call_cerebras(prompt):
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key:
        return None
    body = {
        "model": "llama3.1-70b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 200,
    }
    out = _post_json(
        "https://api.cerebras.ai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body,
    )
    return out["choices"][0]["message"]["content"]


def _call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={key}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    out = _post_json(url, {"Content-Type": "application/json"}, body)
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(prompt):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    body = {
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 200,
    }
    out = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body,
    )
    return out["choices"][0]["message"]["content"]


PROVIDERS = [
    ("groq", _call_groq),
    ("cerebras", _call_cerebras),
    ("gemini", _call_gemini),
    ("openrouter", _call_openrouter),
]


def ask_llm(prompt):
    """
    Try each provider in order. Returns (provider_name, response_text)
    on first success, or (None, None) if every provider is unavailable
    or fails.
    """
    for name, fn in PROVIDERS:
        try:
            result = fn(prompt)
            if result:
                return name, result
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, TimeoutError, RuntimeError) as e:
            print(f"  [llm] {name} failed: {e}")
            continue
    return None, None
