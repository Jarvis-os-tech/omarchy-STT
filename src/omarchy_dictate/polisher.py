"""Fast text structure polishing using Groq and Gemini REST APIs."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
import urllib.error

from .config import Config

POLISH_SYSTEM_PROMPT = """Clean and polish this transcribed speech into clear, well-structured written text.
Rules:
1. Fix punctuation, sentence capitalization, and obvious phonetic speech-to-text typos.
2. Remove hesitation filler words (such as "um", "uh", "ah", "like", "you know" when used as hesitations).
3. If the user spoke multiple sentences, distinct thoughts, or list items, format them cleanly with proper punctuation and natural sentence/paragraph breaks.
4. Strictly preserve ALL sentences and the user's complete meaning. Do NOT summarize, shorten, or omit any content, even for long speeches or many sentences.
5. Return ONLY the polished text. Do NOT include any preamble, explanations, markdown quotes, or commentary."""


def clean_llm_response(text: str) -> str:
    """Strip reasoning tokens or thinking blocks from model responses."""
    # Strip <think>...</think> blocks from models like Qwen or DeepSeek
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip leading/trailing quotes or markdown codeblocks if improperly wrapped
    cleaned = cleaned.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned


async def polish_text(raw_text: str, config: Config) -> str:
    """Polish transcribed text into a clean structure, falling back to raw text on error."""
    text = raw_text.strip()
    if not text or len(text) < 3 or not config.polish or not config.api_key:
        return text

    # Scale timeout with text length for long passages (e.g. 10+ sentences)
    timeout = min(15.0, max(5.0, len(text) / 40.0))
    loop = asyncio.get_running_loop()

    try:
        if config.provider == "groq":
            res = await asyncio.wait_for(
                loop.run_in_executor(None, _call_groq_chat, text, config, timeout),
                timeout=timeout + 0.5,
            )
            if (not res or res == text) and config.gemini_api_key:
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, _call_gemini_rest, text, config, timeout),
                    timeout=timeout + 0.5,
                )
            return res or text
        else:
            res = await asyncio.wait_for(
                loop.run_in_executor(None, _call_gemini_rest, text, config, timeout),
                timeout=timeout + 0.5,
            )
            if (not res or res == text) and config.groq_api_key:
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, _call_groq_chat, text, config, timeout),
                    timeout=timeout + 0.5,
                )
            return res or text
    except Exception:
        # Fallback to raw text so dictation is never lost
        return text


def _call_groq_chat(raw_text: str, config: Config, timeout: float = 5.0) -> str:
    """Polish text using Groq's high-speed chat completion API."""
    key = config.groq_api_key or config.api_key
    if not key:
        return raw_text

    models = [config.polish_model, "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
    seen = set()
    models = [m for m in models if m and not (m in seen or seen.add(m))]

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": f"Raw speech:\n{raw_text}"},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "omarchy-dictate/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    cleaned = clean_llm_response(content)
                    if cleaned:
                        return cleaned
        except Exception:
            continue

    return raw_text


def _call_gemini_rest(raw_text: str, config: Config, timeout: float = 6.0) -> str:
    """Polish text using Google Gemini generateContent."""
    key = config.gemini_api_key or config.api_key
    if not key:
        return raw_text

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.polish_model}:generateContent?key={key}"
    prompt = f"{POLISH_SYSTEM_PROMPT}\n\nRaw speech:\n{raw_text}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "omarchy-dictate/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    polished = parts[0].get("text", "").strip()
                    cleaned = clean_llm_response(polished)
                    if cleaned:
                        return cleaned
    except Exception:
        pass

    return raw_text
