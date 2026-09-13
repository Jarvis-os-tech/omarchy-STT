"""Unit tests for omarchy-dictate."""

import asyncio
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from omarchy_dictate.config import Config, load_config
from omarchy_dictate.polisher import polish_text
from omarchy_dictate.typer import type_text


class ConfigTests(unittest.TestCase):
    def test_default_config(self):
        cfg = Config(api_key="test-key")
        self.assertEqual(cfg.live_model, "gemini-3.5-transcribe-live")
        self.assertEqual(cfg.polish_model, "gemini-flash-latest")
        self.assertEqual(cfg.sample_rate, 16000)
        self.assertEqual(cfg.chunk_ms, 100)
        # 16000 * 0.1 * 2 = 3200 bytes
        self.assertEqual(cfg.chunk_bytes, 3200)

    def test_load_config_reads_env_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "custom_key"}):
            cfg = load_config()
            self.assertEqual(cfg.api_key, "custom_key")


class PolisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_text_returns_immediately(self):
        cfg = Config(api_key="test")
        res = await polish_text("", cfg)
        self.assertEqual(res, "")

    async def test_short_text_returns_immediately(self):
        cfg = Config(api_key="test")
        res = await polish_text("hi", cfg)
        self.assertEqual(res, "hi")

    async def test_polish_disabled_returns_raw(self):
        cfg = Config(api_key="test", polish=False)
        raw = "um test speech"
        res = await polish_text(raw, cfg)
        self.assertEqual(res, raw)


class TyperTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_string_succeeds(self):
        self.assertTrue(await type_text(""))


class TranscriberTests(unittest.TestCase):
    def test_multi_sentence_accumulation(self):
        from omarchy_dictate.live_transcriber import LiveTranscriber
        cfg = Config(api_key="test")
        transcriber = LiveTranscriber(cfg)

        # Simulate 10 sentences arriving across multiple events
        sentences = [f"This is sentence {i}." for i in range(1, 11)]
        for s in sentences:
            if transcriber.finalized_text:
                transcriber.finalized_text += " " + s
            else:
                transcriber.finalized_text = s

        self.assertEqual(
            transcriber.current_transcript,
            " ".join(sentences)
        )
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
        import struct
        # Synthetic 500Hz sine wave PCM
        samples = [int(15000 * math.sin(2 * math.pi * 500 * i / 16000)) for i in range(1600)]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        level = frame_level(pcm)
        self.assertGreater(level, 0.2)
        self.assertLessEqual(level, 1.0)


if __name__ == "__main__":
    import math
    unittest.main()
