"""PipeWire microphone capture for real-time streaming."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from .config import Config


class Microphone:
    """Captures 16-bit mono PCM from PipeWire using pw-record."""

    def __init__(self, config: Config):
        self.config = config
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._running = False

    async def start(self) -> None:
        cmd = [
            "pw-record",
            "--rate", str(self.config.sample_rate),
            "--channels", "1",
            "--format", "s16",
        ]
        if self.config.device:
            cmd.extend(["--target", self.config.device])
        cmd.append("-")

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._running = True

    async def read_chunks(self) -> AsyncIterator[bytes]:
        """Yield raw PCM audio chunks continuously."""
        if not self._proc or not self._proc.stdout:
            return

        chunk_size = self.config.chunk_bytes
        while self._running and self._proc.returncode is None:
            try:
                data = await self._proc.stdout.read(chunk_size)
                if not data:
                    break
                yield data
            except (asyncio.CancelledError, GeneratorExit):
                break
            except Exception:
                break

    async def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
