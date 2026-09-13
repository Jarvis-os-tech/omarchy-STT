"""High-accuracy, ultra-fast speech transcriber supporting Groq Whisper and Gemini."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import urllib.request
import urllib.error
import uuid
import wave
from typing import Callable, Optional

from .audio import Microphone
from .config import Config
from .feedback import Feedback, frame_level

COMMON_SILENCE_HALLUCINATIONS = {
    "thank you.",
    "thank you",
    "thanks for watching.",
    "thanks for watching",
    "you",
    "bye.",
    "subtitles by",
}


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Convert raw 16-bit mono PCM into standard WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def get_audio_energy(pcm: bytes) -> float:
    """Compute average absolute amplitude of PCM samples."""
    if len(pcm) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
    return sum(abs(s) for s in samples) / len(samples)


def has_audio_energy(pcm: bytes, threshold: float = 2.0) -> bool:
    """Check if audio has detectable sound energy (to skip muted mic/silence)."""
    return get_audio_energy(pcm) >= threshold


class LiveTranscriber:
    """Records microphone audio and transcribes via Groq Whisper or Gemini."""

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
            raise ValueError(
                "No API key configured. Please set GROQ_API_KEY or GEMINI_API_KEY in ~/.config/omarchy-dictate/env or .env"
            )

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
        """Stop mic, convert audio to WAV, and transcribe."""
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
        if not pcm_data or len(pcm_data) < 1600 or not has_audio_energy(pcm_data, 2.0):
            return ""

        energy = get_audio_energy(pcm_data)
        wav_bytes = pcm_to_wav(pcm_data, self.config.sample_rate)
        loop = asyncio.get_running_loop()

        text = ""
        try:
            if self.config.provider == "groq":
                text = await loop.run_in_executor(None, self._call_groq_transcribe, wav_bytes)
                if not text and self.config.gemini_api_key:
                    text = await loop.run_in_executor(None, self._call_gemini_transcribe, wav_bytes)
            else:
                text = await loop.run_in_executor(None, self._call_gemini_transcribe, wav_bytes)
                if not text and self.config.groq_api_key:
                    text = await loop.run_in_executor(None, self._call_groq_transcribe, wav_bytes)

            # Suppress silence hallucinations on low-energy clips
            cleaned = text.strip()
            if energy < 15.0 and cleaned.lower() in COMMON_SILENCE_HALLUCINATIONS:
                cleaned = ""

            self.finalized_text = cleaned
            if self.on_text_update and self.finalized_text:
                self.on_text_update(self.finalized_text)
            return self.finalized_text
        except Exception:
            return ""

    def _call_groq_transcribe(self, wav_bytes: bytes) -> str:
        """Call Groq Whisper audio transcriptions API."""
        key = self.config.groq_api_key or self.config.api_key
        if not key:
            return ""

        models = [self.config.live_model, "whisper-large-v3-turbo", "whisper-large-v3"]
        seen = set()
        models = [m for m in models if m and not (m in seen or seen.add(m))]

        for model in models:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body = bytearray()

            def add_field(name: str, val: str) -> None:
                body.extend(f"--{boundary}\r\n".encode("utf-8"))
                body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
                body.extend(val.encode("utf-8"))
                body.extend(b"\r\n")

            add_field("model", model)
            add_field("response_format", "json")
            add_field("temperature", "0.0")

            # WAV file section
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
            body.extend(b"Content-Type: audio/wav\r\n\r\n")
            body.extend(wav_bytes)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode("utf-8"))

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=bytes(body),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "omarchy-dictate/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    text = res.get("text", "").strip()
                    if text:
                        return text
            except Exception:
                continue

        return ""

    def _call_gemini_transcribe(self, wav_bytes: bytes) -> str:
        """Call Google Gemini generateContent with inline audio."""
        key = self.config.gemini_api_key or self.config.api_key
        if not key:
            return ""

        b64 = base64.b64encode(wav_bytes).decode("ascii")
        models = [self.config.live_model, "gemini-flash-latest", "gemini-3.5-transcribe", "gemini-3.6-flash"]
        seen = set()
        models = [m for m in models if m and not (m in seen or seen.add(m))]

        prompt = (
            "You are a speech-to-text engine. Transcribe the spoken audio verbatim with proper punctuation "
            "and capitalization. Output ONLY the transcribed words and nothing else. If background noise or silence only, output nothing."
        )

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
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
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "omarchy-dictate/1.0",
                },
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
