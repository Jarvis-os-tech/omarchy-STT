"""Feedback publisher: controls the on-screen voice flow orb and the status bar label."""

from __future__ import annotations

import array
import json
import math
import os
import time
from pathlib import Path
from typing import Optional

ICONS = {
    "idle": "󰍬",
    "listening": "󰍬",
    "thinking": "󱚟",
    "acting": "󱐋",
    "confirm": "󰀦",
    "error": "󰍭",
}


def frame_level(chunk: bytes) -> float:
    """Loudness of one PCM16 frame as 0..1, shaped for the voice flow orb.

    Every fourth sample is enough for a glow and keeps this off the hot path.
    The square root lifts normal speech into a readable motion range while
    leaving silence/room-tone at 0.
    """
    usable = len(chunk) // 2 * 2
    if usable < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(chunk[:usable])
    window = samples[::4] or samples
    rms = math.sqrt(sum(s * s for s in window) / len(window)) / 32768.0
    value = (rms ** 0.5) * 1.28
    return 0.0 if value < 0.10 else min(1.0, (value - 0.10) / 0.90)


class Feedback:
    """Publishes state and audio loudness to Omarchy shell for VoiceOrb and VoiceIndicator."""

    def __init__(self) -> None:
        uid = os.getuid()
        self.state_dir = Path(f"/run/user/{uid}/omarchy-voice")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "state.json"
        self.level_file = self.state_dir / "level"
        self._last_level_time = 0.0

    def state(self, status: str, text: str = "") -> None:
        """Publish status and label to state.json for the bar widget and voice orb."""
        payload = {
            "status": status,
            "icon": ICONS.get(status, ICONS["idle"]),
            "text": text,
            "class": status,
            "updated": time.time(),
        }
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.state_file)
        except Exception:
            pass

    def level(self, value: float) -> None:
        """Publish 0..1 microphone level for the voice orb animation."""
        now = time.monotonic()
        if now - self._last_level_time < 0.04:  # ~25 Hz update cap
            return
        self._last_level_time = now
        try:
            tmp = self.level_file.with_suffix(".tmp")
            tmp.write_text(f"{value:.2f}\n")
            tmp.replace(self.level_file)
        except Exception:
            pass

    def reset(self) -> None:
        """Reset state to idle and orb to 0."""
        self.state("idle", "")
        try:
            self.level_file.write_text("0.0\n")
        except Exception:
            pass
