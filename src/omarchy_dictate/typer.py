"""Simulates typing into the active focused window using wtype."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess


def sanitize_text_for_typing(text: str) -> str:
    """Ensure text has no newlines or carriage returns that would trigger Enter keypresses."""
    # Replace all newlines, carriage returns, and line breaks with spaces so wtype never emits KEY_ENTER
    text = re.sub(r"[\r\n\v\f]+", " ", text)
    return re.sub(r" +", " ", text).strip()


async def type_text(text: str) -> bool:
    """Type text into the currently active focused Wayland surface, safeguarding via clipboard."""
    text = sanitize_text_for_typing(text)
    if not text:
        return True

    # 1. Safeguard: copy text to clipboard first so long dictations (e.g. 10+ sentences) are never lost
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=2.0)
        except Exception:
            pass

    # 2. Type directly into active focused window via wtype
    if shutil.which("wtype"):
        try:
            # Run in executor to avoid blocking the async event loop
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, _run_wtype, text)
            if res:
                return True
        except Exception:
            pass

    # If wtype was missing, wl-copy succeeded above
    return shutil.which("wl-copy") is not None


def _run_wtype(text: str) -> bool:
    # 2ms delay between characters for reliable ingestion across Wayland/Electron/browsers
    timeout = max(10.0, len(text) * 0.01 + 5.0)
    proc = subprocess.run(
        ["wtype", "-d", "2", "--", text],
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode == 0
