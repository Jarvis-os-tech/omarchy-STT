"""Configuration management for omarchy-dictate."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LIVE_MODEL = "gemini-3.5-transcribe-live"
DEFAULT_POLISH_MODEL = "gemini-flash-latest"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_MS = 100

CONFIG_DIR = Path.home() / ".config" / "omarchy-dictate"
ENV_FILE = CONFIG_DIR / "env"
RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/omarchy-dictate")
SOCKET_FILE = RUNTIME_DIR / "dictate.sock"
PID_FILE = RUNTIME_DIR / "dictate.pid"


@dataclass
class Config:
    api_key: str = ""
    live_model: str = DEFAULT_LIVE_MODEL
    polish_model: str = DEFAULT_POLISH_MODEL
    sample_rate: int = DEFAULT_SAMPLE_RATE
    chunk_ms: int = DEFAULT_CHUNK_MS
    polish: bool = True
    device: str = ""

    @property
    def chunk_bytes(self) -> int:
        # 16-bit mono = 2 bytes per sample
        return int(self.sample_rate * (self.chunk_ms / 1000.0) * 2)


def get_api_key() -> str:
    """Retrieve the Gemini API key from environment or ~/.config/omarchy-dictate/env."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    if ENV_FILE.exists():
        try:
            for line in ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass

    # Fallback to omarchy-voice env if present
    voice_env = Path.home() / ".config" / "omarchy-voice" / "env"
    if voice_env.exists():
        try:
            for line in voice_env.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass

    return ""


def load_config() -> Config:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return Config(
        api_key=get_api_key(),
        live_model=os.environ.get("OMARCHY_DICTATE_LIVE_MODEL", DEFAULT_LIVE_MODEL),
        polish_model=os.environ.get("OMARCHY_DICTATE_POLISH_MODEL", DEFAULT_POLISH_MODEL),
        polish=os.environ.get("OMARCHY_DICTATE_POLISH", "1") not in ("0", "false", "no"),
    )
