"""High-accuracy Gemini audio speech transcriber."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import urllib.request
import urllib.error
import wave
from typing import Callable, Optional

from .audio import Microphone
from .config import Config
from .feedback import Feedback, frame_level


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Convert raw 16-bit mono PCM into standard WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def has_audio_energy(pcm: bytes, threshold: float = 40.0) -> bool:
    """Check if audio has detectable sound energy (to skip muted mic/silence)."""
    if len(pcm) < 2:
        return False
    samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
    avg = sum(abs(s) for s in samples) / len(samples)
    return avg >= threshold


class LiveTranscriber:
    """Records microphone audio and transcribes via Gemini."""

    def __init__(
        self,
        config: Config,
        on_text_update: Optional[Callable[[str], None]] = None,
        feedback: Optional[Feedback] = None,
    ):
        self.config = config
        self.on_text_update = on_text_update
        self.feedback = feedback
        self.mic = Microphone(config)
        self.finalized_text = ""
        self._pcm_buffer = bytearray()
        self._running = False
        self._record_task: Optional[asyncio.Task] = None

    @property
    def current_transcript(self) -> str:
        return self.finalized_text.strip()

    async def start(self) -> None:
        if not self.config.api_key:
            raise ValueError("GEMINI_API_KEY is not configured in ~/.config/omarchy-dictate/env")

        self._running = True
        self._pcm_buffer.clear()
        self.finalized_text = ""

        # Start microphone capture
        await self.mic.start()
        self._record_task = asyncio.create_task(self._record_loop())

    async def _record_loop(self) -> None:
        try:
            async for chunk in self.mic.read_chunks():
                if not self._running:
                    break
                self._pcm_buffer.extend(chunk)
                if self.feedback:
                    self.feedback.level(frame_level(chunk))
        except (asyncio.CancelledError, Exception):
            pass

    async def stop(self) -> str:
        """Stop mic, convert audio to WAV, and transcribe via Gemini."""
        self._running = False
        if self.feedback:
            self.feedback.level(0.0)

        if self._record_task:
            self._record_task.cancel()
            try:
                await self._record_task
            except (asyncio.CancelledError, Exception):
                pass

        await self.mic.stop()

        pcm_data = bytes(self._pcm_buffer)
        if not pcm_data or len(pcm_data) < 1600 or not has_audio_energy(pcm_data, 5.0):
            return ""

        # Package as WAV and send to Gemini
        wav_bytes = pcm_to_wav(pcm_data, self.config.sample_rate)
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(
                None,
                self._call_gemini_transcribe,
                wav_bytes,
            )
            self.finalized_text = text.strip()
            if self.on_text_update and self.finalized_text:
                self.on_text_update(self.finalized_text)
            return self.finalized_text
        except Exception:
            return ""

    def _call_gemini_transcribe(self, wav_bytes: bytes) -> str:
        b64 = base64.b64encode(wav_bytes).decode("ascii")

        # Models to try: gemini-flash-latest (fastest & robust), gemini-3.5-transcribe, gemini-3.6-flash
        models = ["gemini-flash-latest", "gemini-3.5-transcribe", "gemini-3.6-flash"]
        prompt = (
            "You are a speech-to-text engine. Transcribe the spoken audio verbatim with proper punctuation "
            "and capitalization. Output ONLY the transcribed words and nothing else. If background noise or silence only, output nothing."
        )

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.config.api_key}"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "audio/wav", "data": b64}}
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.0,
                }
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    candidates = res.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        extracted = []
                        for part in parts:
                            if isinstance(part, dict):
                                if "text" in part and part["text"]:
                                    extracted.append(part["text"])
                                elif "audioTranscription" in part:
                                    t = part["audioTranscription"].get("text", "")
                                    if t:
                                        extracted.append(t)
                        result = " ".join(extracted).strip()
                        if result:
                            return result
            except Exception:
                continue

        return ""
