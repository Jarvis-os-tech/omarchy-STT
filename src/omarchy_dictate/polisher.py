"""Fast text structure polishing using Gemini REST API."""

from __future__ import annotations

import asyncio
import json
import urllib.request
import urllib.error

from .config import Config

POLISH_SYSTEM_PROMPT = """Clean and polish this transcribed speech into clear, well-structured written text.
Rules:
1. Fix punctuation, sentence capitalization, and obvious phonetic speech-to-text typos.
2. Remove hesitation filler words (such as "um", "uh", "ah", "like", "you know" when used as hesitations).
3. If the user spoke multiple sentences, distinct thoughts, or list items, format them cleanly with proper punctuation and natural sentence/paragraph breaks.
4. Strictly preserve ALL sentences and the user's complete meaning. Do NOT summarize, shorten, or omit any content, even for long speeches or many sentences.
5. Return ONLY the polished text. Do NOT include any preamble, explanations, markdown quotes, or commentary.

Raw speech:
{raw_text}"""


async def polish_text(raw_text: str, config: Config) -> str:
    """Polish transcribed text into a clean structure, falling back to raw text on error."""
    text = raw_text.strip()
    if not text or len(text) < 3 or not config.polish or not config.api_key:
        return text

    # Scale timeout with text length for long passages (e.g. 10+ sentences)
    timeout = min(15.0, max(6.0, len(text) / 40.0))
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _call_gemini_rest, text, config, timeout),
            timeout=timeout + 0.5,
        )
    except Exception:
        # Fallback to raw text so dictation is never lost
        return text


def _call_gemini_rest(raw_text: str, config: Config, timeout: float = 6.0) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.polish_model}:generateContent?key={config.api_key}"
    prompt = POLISH_SYSTEM_PROMPT.format(raw_text=raw_text)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                polished = parts[0].get("text", "").strip()
                if polished:
                    return polished

    return raw_text
