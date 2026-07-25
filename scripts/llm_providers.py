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


def _post_json(url, headers, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_groq(prompt):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
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
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, TimeoutError) as e:
            print(f"  [llm] {name} failed: {e}")
            continue
    return None, None
