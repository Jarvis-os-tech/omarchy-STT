"""Dictation session coordinator: connects transcriber, polisher, and typer without floating bars."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from typing import Optional

from .config import Config, PID_FILE, SOCKET_FILE
from .feedback import Feedback
from .live_transcriber import LiveTranscriber
from .polisher import polish_text
from .typer import type_text


import atexit


def send_notification(title: str, message: str, timeout_ms: int = 3000) -> None:
    """Send a non-blocking desktop notification."""
    try:
        subprocess.Popen(
            [
                "notify-send",
                "-a", "Omarchy Dictate",
                "-t", str(timeout_ms),
                "-u", "low",
                "--",
                title,
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def play_sound(sound_name: str = "audio-volume-change") -> None:
    """Play a non-blocking audio chime."""
    sound_path = f"/usr/share/sounds/freedesktop/stereo/{sound_name}.oga"
    if os.path.exists(sound_path):
        try:
            subprocess.Popen(
                ["pw-play", sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            pass

    try:
        subprocess.Popen(
            ["canberra-gtk-play", "-i", sound_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


import socket
from pathlib import Path

from .ui import FloatingPillWindow


def mute_voice_agent() -> bool:
    """If omarchy-voice daemon is running, mute it so it won't listen/type during dictation."""
    agent_sock = Path(f"/run/user/{os.getuid()}/omarchy-voice/control.sock")
    if not agent_sock.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.4)
        s.connect(str(agent_sock))
        s.sendall(b"mute\n")
        s.recv(64)
        s.close()
        return True
    except Exception:
        return False


def unmute_voice_agent() -> None:
    """Restore omarchy-voice when dictation finishes."""
    agent_sock = Path(f"/run/user/{os.getuid()}/omarchy-voice/control.sock")
    if not agent_sock.exists():
        return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.4)
        s.connect(str(agent_sock))
        s.sendall(b"unmute\n")
        s.recv(64)
        s.close()
    except Exception:
        pass


def bind_stop_keys() -> None:
    """Dynamically bind Return, KP_Enter, and Escape in Hyprland while dictating."""
    cmd = (
        'local keys = { "RETURN", "code:36", "KP_ENTER", "code:104", "Return", "KP_Enter" }; '
        'for _, k in ipairs(keys) do '
        '  pcall(o.bind, k, "Stop voice dictation", "linux-voice stop"); '
        'end; '
        'local esc_keys = { "ESCAPE", "code:9", "Escape" }; '
        'for _, k in ipairs(esc_keys) do '
        '  pcall(o.bind, k, "Cancel voice dictation", "linux-voice cancel"); '
        'end'
    )
    try:
        subprocess.run(["hyprctl", "eval", cmd], capture_output=True, timeout=1.0)
    except Exception:
        pass


def unbind_stop_keys() -> None:
    """Unconditionally restore Return, KP_Enter, and Escape in Hyprland."""
    cmd = (
        'local keys = { "RETURN", "code:36", "KP_ENTER", "code:104", "Return", "KP_Enter", "ESCAPE", "code:9", "Escape" }; '
        'for _, k in ipairs(keys) do '
        '  for i = 1, 3 do '
        '    pcall(hl.unbind, k); '
        '  end '
        'end'
    )
    try:
        subprocess.run(["hyprctl", "eval", cmd], capture_output=True, timeout=1.0)
    except Exception:
        pass


# Register atexit handler so Enter is guaranteed restored if the process terminates
atexit.register(unbind_stop_keys)


class DictationSession:
    """Manages an active dictation lifecycle from Super+H to Enter/typing without floating bars."""

    def __init__(self, config: Config):
        self.config = config
        self.feedback = Feedback()
        self.pill: Optional[FloatingPillWindow] = None
        self._muted_agent = False
        self.transcriber: Optional[LiveTranscriber] = None
        self._server: Optional[asyncio.Server] = None
        self._stop_event = asyncio.Event()
        self._cancelled = False

    def _handle_signal(self) -> None:
        unbind_stop_keys()
        self._stop_event.set()

    def _handle_cancel_from_ui(self) -> None:
        self._cancelled = True
        self._stop_event.set()

    async def run(self) -> None:
        """Run the dictation session until stopped via Enter or Super+H."""
        # Always clean any leftover stop binds before doing anything
        unbind_stop_keys()
        self.feedback.reset()

        # Mute omarchy-voice if running so it never listens or types while we dictate
        self._muted_agent = mute_voice_agent()

        try:
            # 1. Write PID file
            PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(os.getpid()))

            # 2. Start Control Socket Server for toggle/stop signaling
            await self._start_socket_server()

            # 3. IMMEDIATELY bind Return/Enter and Escape so keys respond with zero lag
            bind_stop_keys()

            # 4. Start Floating Pill overlay on screen with direct Enter & Esc capture
            try:
                self.pill = FloatingPillWindow(
                    on_stop=lambda: self._stop_event.set(),
                    on_cancel=self._handle_cancel_from_ui,
                )
                self.pill.start()
            except Exception:
                self.pill = None

            # 5. Start Live Streaming Transcriber and Microphone
            self.transcriber = LiveTranscriber(
                config=self.config,
                on_text_update=None,
                feedback=self.feedback,
            )
            await self.transcriber.start()
            play_sound("audio-volume-change")
            provider_label = "Groq" if self.config.provider == "groq" else "Gemini"
            send_notification(
                f"🎙️ Voice Dictation Active ({provider_label})",
                "Listening... Speak now.\nPress Enter to finish, or Super+H to stop.",
            )

            # 6. Set up signal handlers to cleanly unbind and stop
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                try:
                    loop.add_signal_handler(sig, self._handle_signal)
                except (NotImplementedError, RuntimeError):
                    pass

            # 7. Wait until stop signal with 120s safety timeout to prevent permanent Enter hijacking
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                pass

            # 8. IMMEDIATELY unbind stop keys as first action so Enter is released to normal use
            unbind_stop_keys()
            play_sound("audio-volume-change")

            # 9. Update visual pill to polishing state
            if self.pill and not self._cancelled:
                self.pill.set_polishing()

            # 10. Stop dictation, polish, and type text into the active text bar
            if not self._cancelled:
                send_notification(f"✓ Transcribing ({provider_label})...", "Converting speech to text...")
                await self._finish()
            else:
                send_notification("✕ Cancelled", "Voice dictation cancelled.")

        except Exception as e:
            send_notification("⚠️ Dictation Error", str(e))
            raise
        finally:
            # Defensive restore of Hyprland keybinds, close pill, unmute voice agent
            unbind_stop_keys()
            if self.pill:
                try:
                    self.pill.close()
                except Exception:
                    pass
                self.pill = None
            if self._muted_agent:
                unmute_voice_agent()
                self._muted_agent = False
            self.feedback.reset()
            self._cleanup()

    async def _finish(self) -> None:
        """Collect transcript, polish text, and type directly into the focused text bar."""
        raw_transcript = ""
        if self.transcriber:
            raw_transcript = await self.transcriber.stop()

        # Polish text via Gemini REST (fixes grammar, punctuation, preserves 10+ sentences)
        polished_text = raw_transcript
        if raw_transcript.strip():
            polished_text = await polish_text(raw_transcript, self.config)

        # Close visual pill BEFORE typing so window focus is 100% active on the text bar!
        if self.pill:
            try:
                self.pill.close()
            except Exception:
                pass
            self.pill = None

        # Give Hyprland 150ms to ensure the window has full keyboard focus
        await asyncio.sleep(0.15)

        # Type directly into the active focused window / text bar
        if polished_text.strip():
            preview = polished_text[:40] + "..." if len(polished_text) > 40 else polished_text
            send_notification("✓ Dictated", preview, timeout_ms=2500)
            await type_text(polished_text)
        else:
            send_notification("Linux Voice", "No speech detected", timeout_ms=2000)

        # Unmute voice agent as soon as typing completes
        if self._muted_agent:
            unmute_voice_agent()
            self._muted_agent = False

    async def _start_socket_server(self) -> None:
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except OSError:
                pass

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(SOCKET_FILE),
        )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            data = await reader.read(128)
            cmd = data.decode("utf-8", errors="ignore").strip()
            if cmd == "cancel":
                self._cancelled = True
                self._stop_event.set()
                writer.write(b"ok\n")
            elif cmd in ("stop", "toggle"):
                self._stop_event.set()
                writer.write(b"ok\n")
            elif cmd == "status":
                writer.write(b"recording\n")
            else:
                writer.write(b"unknown\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _cleanup(self) -> None:
        if self._server:
            self._server.close()
            self._server = None
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except OSError:
                pass
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
