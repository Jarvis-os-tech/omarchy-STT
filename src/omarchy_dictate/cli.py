"""Command-line interface for omarchy-dictate."""

from __future__ import annotations

import asyncio
import fcntl
import os
import socket
import sys
import time
from typing import Optional

from .config import RUNTIME_DIR, SOCKET_FILE, PID_FILE, LOCK_FILE, load_config
from .session import DictationSession, unbind_stop_keys


def acquire_instance_lock() -> Optional[int]:
    """Acquire exclusive non-blocking lock on LOCK_FILE. Returns fd if acquired, else None."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        return None


def release_instance_lock(fd: Optional[int]) -> None:
    """Release instance lock and close fd."""
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass
        if LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass


def send_command(cmd: str, timeout: float = 1.5) -> bool:
    """Send command to running dictation session over UNIX socket."""
    if not SOCKET_FILE.exists():
        return False

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(str(SOCKET_FILE))
        sock.sendall(f"{cmd}\n".encode("utf-8"))
        res = sock.recv(64)
        sock.close()
        return res.strip() == b"ok"
    except (socket.error, OSError):
        return False


def is_running() -> bool:
    """Check if an active dictation session is running."""
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        # Lock is held -> definitely running!
        return True
    # Lock was not held -> release immediately
    release_instance_lock(lock_fd)
    return False


def cmd_toggle() -> int:
    """Toggle dictation on or off with strict single-instance guarantee."""
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        # An instance is already running or starting up!
        # Tell the running instance to toggle (stop & finish)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if send_command("toggle", timeout=1.0):
                unbind_stop_keys()
                return 0
            time.sleep(0.05)
        # Never spawn a duplicate session
        unbind_stop_keys()
        return 0

    # We acquired the lock -> We are the ONE AND ONLY dictation instance!
    try:
        unbind_stop_keys()
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
    finally:
        release_instance_lock(lock_fd)


def cmd_start() -> int:
    """Start dictation if not already running."""
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        # Already running
        return 0

    try:
        unbind_stop_keys()
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
    finally:
        release_instance_lock(lock_fd)


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
