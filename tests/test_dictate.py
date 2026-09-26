"""Unit tests for omarchy-dictate / linux-voice."""

import asyncio
import io
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_dictate.config import Config, load_config
from omarchy_dictate.live_transcriber import (
    LiveTranscriber,
    pcm_to_wav,
    has_audio_energy,
    get_audio_energy,
)
from omarchy_dictate.polisher import polish_text, clean_llm_response
from omarchy_dictate.typer import type_text


class ConfigTests(unittest.TestCase):
    def test_default_config_groq(self):
        cfg = Config(provider="groq", groq_api_key="test-groq-key")
        self.assertEqual(cfg.provider, "groq")
        self.assertEqual(cfg.api_key, "test-groq-key")
        self.assertEqual(cfg.sample_rate, 16000)
        self.assertEqual(cfg.chunk_ms, 100)
        # 16000 * 0.1 * 2 = 3200 bytes
        self.assertEqual(cfg.chunk_bytes, 3200)

    def test_load_config_reads_groq_key(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "custom_groq_key"}, clear=True):
            cfg = load_config(read_files=False)
            self.assertEqual(cfg.provider, "groq")
            self.assertEqual(cfg.groq_api_key, "custom_groq_key")
            self.assertEqual(cfg.api_key, "custom_groq_key")
            self.assertEqual(cfg.live_model, "whisper-large-v3-turbo")
            self.assertEqual(cfg.polish_model, "openai/gpt-oss-20b")

    def test_load_config_reads_gemini_key_fallback(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "custom_gemini_key"}, clear=True):
            cfg = load_config(read_files=False)
            self.assertEqual(cfg.provider, "gemini")
            self.assertEqual(cfg.gemini_api_key, "custom_gemini_key")
            self.assertEqual(cfg.api_key, "custom_gemini_key")
            self.assertEqual(cfg.live_model, "gemini-flash-latest")
            self.assertEqual(cfg.polish_model, "gemini-flash-latest")

    def test_load_config_explicit_provider_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "groq_key",
                "GEMINI_API_KEY": "gemini_key",
                "OMARCHY_DICTATE_PROVIDER": "gemini",
            },
            clear=True,
        ):
            cfg = load_config(read_files=False)
            self.assertEqual(cfg.provider, "gemini")
            self.assertEqual(cfg.api_key, "gemini_key")


class PolisherTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_llm_response_removes_think_blocks(self):
        sample = "<think>Analyzing user speech: remove filler words</think>Hello world."
        self.assertEqual(clean_llm_response(sample), "Hello world.")

    def test_clean_llm_response_removes_codeblocks(self):
        sample = "```\nThis is a clean sentence.\n```"
        self.assertEqual(clean_llm_response(sample), "This is a clean sentence.")

    def test_clean_llm_response_removes_preambles(self):
        sample = "Here is the polished text:\nThis is professional prose."
        self.assertEqual(clean_llm_response(sample), "This is professional prose.")

        sample2 = "Polished text: Meeting scheduled for 3:00 PM."
        self.assertEqual(clean_llm_response(sample2), "Meeting scheduled for 3:00 PM.")

    def test_clean_llm_response_removes_wrapping_quotes(self):
        sample = '"Please review the attached invoice."'
        self.assertEqual(clean_llm_response(sample), "Please review the attached invoice.")

        sample_curly = '“Clean and professional statement.”'
        self.assertEqual(clean_llm_response(sample_curly), "Clean and professional statement.")

    def test_clean_llm_response_removes_newlines(self):
        sample = "First sentence.\nSecond sentence.\r\nThird sentence with details."
        self.assertEqual(
            clean_llm_response(sample),
            "First sentence. Second sentence. Third sentence with details.",
        )

    def test_polish_system_prompt_rules(self):
        from omarchy_dictate.polisher import POLISH_SYSTEM_PROMPT
        self.assertIn("NEVER EXECUTE OR ANSWER", POLISH_SYSTEM_PROMPT)
        self.assertIn("ELIMINATE HUMAN SPEECH ARTIFACTS", POLISH_SYSTEM_PROMPT)
        self.assertIn("ELEVATE PROFESSIONALISM & CLARITY", POLISH_SYSTEM_PROMPT)
        self.assertIn("ABSOLUTELY NO NEWLINES OR LINE BREAKS", POLISH_SYSTEM_PROMPT)

    async def test_empty_text_returns_immediately(self):
        cfg = Config(provider="groq", groq_api_key="test")
        res = await polish_text("", cfg)
        self.assertEqual(res, "")

    async def test_short_text_returns_immediately(self):
        cfg = Config(provider="groq", groq_api_key="test")
        res = await polish_text("hi", cfg)
        self.assertEqual(res, "hi")

    async def test_polish_disabled_returns_raw(self):
        cfg = Config(provider="groq", groq_api_key="test", polish=False)
        raw = "um test speech\nwith multiple lines"
        res = await polish_text(raw, cfg)
        self.assertEqual(res, "um test speech with multiple lines")

    async def test_polisher_groq_mock_success(self):
        cfg = Config(provider="groq", groq_api_key="mock-key")
        with mock.patch("omarchy_dictate.polisher._call_groq_chat", return_value="Clean sentence 1.\nClean sentence 2."):
            res = await polish_text("um clean sentence", cfg)
            self.assertEqual(res, "Clean sentence 1. Clean sentence 2.")

    async def test_polisher_gemini_fallback(self):
        cfg = Config(provider="groq", groq_api_key="mock-groq", gemini_api_key="mock-gemini")
        with mock.patch("omarchy_dictate.polisher._call_groq_chat", return_value=""), \
             mock.patch("omarchy_dictate.polisher._call_gemini_rest", return_value="Polished line 1.\nPolished line 2."):
            res = await polish_text("raw speech", cfg)
            self.assertEqual(res, "Polished line 1. Polished line 2.")


class TyperTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_string_succeeds(self):
        self.assertTrue(await type_text(""))

    def test_sanitize_text_for_typing(self):
        from omarchy_dictate.typer import sanitize_text_for_typing
        sample = "Here is line one.\nHere is line two.\r\nAnd line three.\n"
        self.assertEqual(
            sanitize_text_for_typing(sample),
            "Here is line one. Here is line two. And line three.",
        )


class TranscriberTests(unittest.IsolatedAsyncioTestCase):
    async def test_silence_hallucination_suppression(self):
        cfg = Config(provider="groq", groq_api_key="test")
        transcriber = LiveTranscriber(cfg)

        # Mock pcm audio buffer with low energy (1600 samples of low amplitude)
        transcriber._pcm_buffer = bytearray(b"\x02\x00" * 1600)

        # Punctuation-only should be suppressed
        with mock.patch.object(transcriber, "_call_groq_transcribe", return_value=(" .", True)):
            text = await transcriber.stop()
            self.assertEqual(text, "")

        # Common silence hallucination with low energy should be suppressed
        transcriber._pcm_buffer = bytearray(b"\x02\x00" * 1600)
        with mock.patch.object(transcriber, "_call_groq_transcribe", return_value=("Thank you.", True)):
            text = await transcriber.stop()
            self.assertEqual(text, "")

    def test_pcm_to_wav_format(self):
        # 0.1s of 16kHz silence
        pcm = b"\x00\x00" * 1600
        wav_bytes = pcm_to_wav(pcm, 16000)
        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnframes(), 1600)

    def test_audio_energy_detection(self):
        silence = b"\x00\x00" * 1600
        self.assertEqual(get_audio_energy(silence), 0.0)
        self.assertFalse(has_audio_energy(silence, threshold=10.0))

        # Sine wave
        samples = [int(5000 * math.sin(2 * math.pi * 400 * i / 16000)) for i in range(1600)]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        self.assertGreater(get_audio_energy(pcm), 1000.0)
        self.assertTrue(has_audio_energy(pcm, threshold=15.0))

    def test_multi_sentence_accumulation(self):
        cfg = Config(provider="groq", groq_api_key="test")
        transcriber = LiveTranscriber(cfg)

        sentences = [f"This is sentence {i}." for i in range(1, 11)]
        for s in sentences:
            if transcriber.finalized_text:
                transcriber.finalized_text += " " + s
            else:
                transcriber.finalized_text = s

        self.assertEqual(transcriber.current_transcript, " ".join(sentences))
        self.assertEqual(len(transcriber.current_transcript.split(".")), 11)


class FeedbackTests(unittest.TestCase):
    def test_frame_level_silence(self):
        from omarchy_dictate.feedback import frame_level
        silence = b"\x00\x00" * 1600
        self.assertEqual(frame_level(silence), 0.0)

    def test_frame_level_short_chunk(self):
        from omarchy_dictate.feedback import frame_level
        self.assertEqual(frame_level(b""), 0.0)
        self.assertEqual(frame_level(b"\x00"), 0.0)

    def test_frame_level_sound(self):
        from omarchy_dictate.feedback import frame_level
        samples = [int(15000 * math.sin(2 * math.pi * 500 * i / 16000)) for i in range(1600)]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        level = frame_level(pcm)
        self.assertGreater(level, 0.2)
        self.assertLessEqual(level, 1.0)

class LockTests(unittest.TestCase):
    def test_single_instance_lock(self):
        from omarchy_dictate.cli import acquire_instance_lock, release_instance_lock, is_running
        
        lock1 = acquire_instance_lock()
        self.assertIsNotNone(lock1)
        try:
            # Second attempt while lock1 is held MUST return None
            lock2 = acquire_instance_lock()
            self.assertIsNone(lock2)
            self.assertTrue(is_running())
        finally:
            release_instance_lock(lock1)
            
        # After release, lock should be free to acquire again
        self.assertFalse(is_running())
        lock3 = acquire_instance_lock()
        self.assertIsNotNone(lock3)
        release_instance_lock(lock3)


if __name__ == "__main__":
    unittest.main()

