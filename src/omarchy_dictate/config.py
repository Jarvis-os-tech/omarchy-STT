"""Configuration management for omarchy-dictate / linux-voice."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# Default models
DEFAULT_GROQ_STT_MODEL = "whisper-large-v3-turbo"
DEFAULT_GROQ_POLISH_MODEL = "openai/gpt-oss-20b"

DEFAULT_GEMINI_STT_MODEL = "gemini-flash-latest"
DEFAULT_GEMINI_POLISH_MODEL = "gemini-flash-latest"

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_MS = 100

CONFIG_DIR = Path.home() / ".config" / "omarchy-dictate"
ENV_FILE = CONFIG_DIR / "env"
RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/omarchy-dictate")
SOCKET_FILE = RUNTIME_DIR / "dictate.sock"
PID_FILE = RUNTIME_DIR / "dictate.pid"
LOCK_FILE = RUNTIME_DIR / "dictate.lock"
STATE_DIR = Path.home() / ".local" / "state" / "linux-voice"
LOG_FILE = STATE_DIR / "dictate.log"


def setup_logging():
    """Configure lightweight logging to ~/.local/state/linux-voice/dictate.log."""
    import logging
    logger = logging.getLogger("omarchy_dictate")
    if not logger.handlers:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            logger.setLevel(logging.INFO)
            fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
            fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass
    return logger



@dataclass
class Config:
    provider: str = "groq"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    live_model: str = ""
    polish_model: str = ""
    sample_rate: int = DEFAULT_SAMPLE_RATE
    chunk_ms: int = DEFAULT_CHUNK_MS
    polish: bool = True
    device: str = ""

    @property
    def api_key(self) -> str:
        """Return the API key corresponding to the active provider."""
        if self.provider == "groq":
            return self.groq_api_key or self.gemini_api_key
        return self.gemini_api_key or self.groq_api_key

    @property
    def chunk_bytes(self) -> int:
        # 16-bit mono = 2 bytes per sample
        return int(self.sample_rate * (self.chunk_ms / 1000.0) * 2)


def _read_env_file(path: Path) -> Dict[str, str]:
    """Parse a simple KEY=VALUE file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return values


def load_env_variables(env_file: Optional[Path] = None, read_files: bool = True) -> Dict[str, str]:
    """Load configuration variables with priority:
    1. System environment variables
    2. Local .env in current directory or project root
    3. User configuration ~/.config/omarchy-dictate/env or ~/.config/linux-voice/env
    4. Fallback ~/.config/omarchy-voice/env
    """
    merged: Dict[str, str] = {}

    if read_files:
        if env_file:
            candidates = [env_file]
        else:
            candidates = [
                Path.home() / ".config" / "omarchy-voice" / "env",
                Path.home() / ".config" / "linux-voice" / "env",
                ENV_FILE,
                Path.cwd() / ".env",
                Path(__file__).resolve().parent.parent.parent / ".env",
            ]

        for candidate in candidates:
            if candidate.exists():
                merged.update(_read_env_file(candidate))

    # Process environment takes top priority
    for key in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "OMARCHY_DICTATE_PROVIDER",
        "VOICE_PROVIDER",
        "OMARCHY_DICTATE_LIVE_MODEL",
        "OMARCHY_DICTATE_POLISH_MODEL",
        "OMARCHY_DICTATE_POLISH",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            merged[key] = val

    return merged


def load_config(read_files: bool = True, env_file: Optional[Path] = None) -> Config:
    """Instantiate a Config object populated from environment or config files."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env_variables(env_file=env_file, read_files=read_files)

    groq_key = env.get("GROQ_API_KEY", "").strip()
    gemini_key = env.get("GEMINI_API_KEY", "").strip()

    # Determine provider: user specified, or auto-detect based on available keys
    preferred = env.get("OMARCHY_DICTATE_PROVIDER", env.get("VOICE_PROVIDER", "")).strip().lower()
    if preferred in ("groq", "gemini"):
        provider = preferred
    elif groq_key:
        provider = "groq"
    elif gemini_key:
        provider = "gemini"
    else:
        provider = "groq"

    # Set default models per provider
    if provider == "groq":
        default_live = DEFAULT_GROQ_STT_MODEL
        default_polish = DEFAULT_GROQ_POLISH_MODEL
    else:
        default_live = DEFAULT_GEMINI_STT_MODEL
        default_polish = DEFAULT_GEMINI_POLISH_MODEL

    live_model = env.get("OMARCHY_DICTATE_LIVE_MODEL", default_live)
    polish_model = env.get("OMARCHY_DICTATE_POLISH_MODEL", default_polish)
    polish_enabled = env.get("OMARCHY_DICTATE_POLISH", "1").lower() not in ("0", "false", "no")

    return Config(
        provider=provider,
        groq_api_key=groq_key,
        gemini_api_key=gemini_key,
        live_model=live_model,
        polish_model=polish_model,
        polish=polish_enabled,
    )
