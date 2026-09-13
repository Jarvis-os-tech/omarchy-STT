# Linux Voice Dictation (`linux-voice` / `omarchy-dictate`)

A real-time, low-latency voice dictation system for Linux and Hyprland / Wayland powered by **Groq Whisper** and **Google Gemini**.

## Features

- **Blazing Fast Transcription**: Powered by Groq's `whisper-large-v3-turbo` with sub-second turnaround, with full fallback support for Google Gemini.
- **Smart Text Polisher**: Automatically formats punctuation, capitalization, and paragraph flow, strips hesitation filler words (`um`, `uh`, `like`), and preserves 100% of your multi-sentence dictation using Groq / Gemini LLMs.
- **Press & Release Hotkey**: Press `SUPER + H` to start listening continuously.
- **On-Screen Voice Flow Orb**: A glowing, breathing voice orb overlay at the bottom of the screen that visualizes your speech loudness in real-time.
- **Top Bar Status**: Integrates with Omarchy's bar widget (`voice.indicator`) showing live microphone status.
- **Enter to Stop & Type**: Pressing `ENTER` stops listening, transcribes verbatim, polishes punctuation/formatting, and types directly into the focused application or text bar.
- **Normal Enter Isolation**: When voice dictation is not active, the `ENTER` key is 100% untouched and operates normally for all applications.
- **Escape to Cancel**: Press `ESCAPE` while listening to cancel without typing.
- **Multi-Sentence Support**: Capable of capturing 10+ sentences or full paragraphs accurately without summarizing.
- **Clipboard Backup**: Text is automatically copied to the clipboard (`wl-copy`) simultaneously so nothing is ever lost.

## Requirements

- Python 3.10+
- PipeWire (`pw-record`, `pw-play`)
- Wayland tools (`wtype`, `wl-clipboard`)
- `notify-send` (libnotify)
- API Key: **Groq API Key** (recommended for ultra-fast STT) or **Google Gemini API Key**

## Installation

1. Clone and run the installer:
   ```bash
   ./install.sh
   ```

2. Configure your API key in `~/.config/omarchy-dictate/env` (or a local `.env` file):
   ```bash
   # Groq API Key (Recommended: Fastest Whisper STT & LLM Polisher)
   GROQ_API_KEY=gsk_...

   # Google Gemini API Key (Alternative / Fallback)
   GEMINI_API_KEY=AIzaSy...
   ```

3. Ensure the Hyprland binding is in `~/.config/hypr/bindings.lua`:
   ```lua
   if o.cmd_present("linux-voice") or o.cmd_present("omarchy-dictate") then
     o.bind("SUPER + H", "Voice dictation", "linux-voice toggle")
     o.bind("SUPER + h", "Voice dictation", "linux-voice toggle")
   end
   ```
   Then reload Hyprland:
   ```bash
   hyprctl reload
   ```

## Usage

- **Start / Stop**: Press `SUPER + H` or run `linux-voice toggle`
- **Stop & Type**: Press `ENTER` while dictating or run `linux-voice stop`
- **Cancel**: Press `ESCAPE` while dictating or run `linux-voice cancel`
- **Status**: Run `linux-voice status` (returns `recording` or `idle`)
- **Emergency Unbind**: Run `linux-voice unbind` to ensure Enter/Escape are completely unbound

## Testing

Run unit tests with:
```bash
python3 -m unittest discover tests
```
