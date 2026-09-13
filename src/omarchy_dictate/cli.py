"""Command-line interface for omarchy-dictate."""

from __future__ import annotations

import asyncio
import os
import socket
import sys

from .config import SOCKET_FILE, PID_FILE, load_config
from .session import DictationSession, unbind_stop_keys


def send_command(cmd: str) -> bool:
    """Send command to running dictation session over UNIX socket."""
    if not SOCKET_FILE.exists():
        return False

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(str(SOCKET_FILE))
        sock.sendall(f"{cmd}\n".encode("utf-8"))
        res = sock.recv(64)
        sock.close()
        return res.strip() == b"ok"
    except (socket.error, OSError):
        try:
            SOCKET_FILE.unlink()
        except OSError:
            pass
        return False


def is_running() -> bool:
    """Check if an active dictation session is running."""
    if not SOCKET_FILE.exists():
        return False

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.connect(str(SOCKET_FILE))
        sock.sendall(b"status\n")
        res = sock.recv(64)
        sock.close()
        return res.strip() == b"recording"
    except (socket.error, OSError):
        try:
            SOCKET_FILE.unlink()
        except OSError:
            pass
        return False


def cmd_toggle() -> int:
    """Toggle dictation on or off."""
    if SOCKET_FILE.exists():
        if send_command("toggle"):
            unbind_stop_keys()
            return 0

    # Ensure clean state before starting
    unbind_stop_keys()

    # Start new session
    config = load_config()
    session = DictationSession(config)
    try:
        asyncio.run(session.run())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Error starting dictation: {e}", file=sys.stderr)
        return 1
    finally:
        unbind_stop_keys()


def cmd_stop() -> int:
    try:
        send_command("stop")
    finally:
        # Guarantee Return key is NEVER stuck bound
        unbind_stop_keys()
    return 0


def cmd_cancel() -> int:
    try:
        send_command("cancel")
    finally:
        unbind_stop_keys()
    return 0


def cmd_unbind() -> int:
    """Explicitly restore normal Return and Escape keys."""
    unbind_stop_keys()
    print("Restored Enter and Escape keys in Hyprland.")
    return 0


def cmd_status() -> int:
    if is_running():
        print("recording")
    else:
        print("idle")
    return 0


def main() -> int:
    args = sys.argv[1:]
    command = args[0] if args else "toggle"

    if command in ("toggle", "start"):
        if command == "start" and is_running():
            return 0
        return cmd_toggle()
    elif command == "stop":
        return cmd_stop()
    elif command == "cancel":
        return cmd_cancel()
    elif command == "unbind":
        return cmd_unbind()
    elif command == "status":
        return cmd_status()
    elif command in ("-h", "--help", "help"):
        print("Usage: linux-voice [toggle|start|stop|cancel|unbind|status]")
        print("  toggle  Start dictation or stop & type active transcript (default)")
        print("  start   Start dictation if not already running")
        print("  stop    Stop active dictation session and type text")
        print("  cancel  Cancel active session without typing")
        print("  unbind  Force restore Enter and Escape keys")
        print("  status  Check current status (recording/idle)")
        return 0
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
