# Linux Voice Dictation (`linux-voice`)

A real-time, low-latency voice dictation system for Linux and Hyprland / Wayland powered by Google Gemini.

## Features

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
- Google Gemini API Key

## Installation

1. Run the installer:
   ```bash
   ./install.sh
   ```

2. Add your Gemini API Key in `~/.config/omarchy-dictate/env`:
   ```bash
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
