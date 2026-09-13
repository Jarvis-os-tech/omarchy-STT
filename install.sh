#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE_DIR="$HOME/.local/share/linux-voice"
LEGACY_SHARE_DIR="$HOME/.local/share/omarchy-dictate"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/omarchy-dictate"
PLUGIN_DIR="$HOME/.config/omarchy/plugins"

echo "========================================="
echo "   Installing Linux Voice Dictation      "
echo "========================================="

# 1. Directories
mkdir -p "$SHARE_DIR" "$BIN_DIR" "$CONFIG_DIR" "$PLUGIN_DIR" "$HOME/.config/linux-voice"

# 2. Copy source and binary files
cp -r "$SCRIPT_DIR/src" "$SCRIPT_DIR/bin" "$SHARE_DIR/"
ln -sf "$SHARE_DIR" "$LEGACY_SHARE_DIR"

# 3. Create command-line binaries
ln -sf "$SHARE_DIR/bin/linux-voice" "$BIN_DIR/linux-voice"
ln -sf "$SHARE_DIR/bin/omarchy-dictate" "$BIN_DIR/omarchy-dictate"
chmod +x "$SHARE_DIR/bin/linux-voice" "$SHARE_DIR/bin/omarchy-dictate"

# 4. Install Omarchy Quickshell plugins (Voice Flow Orb & Bar Indicator)
if [ -d "$SCRIPT_DIR/plugin" ]; then
  cp -r "$SCRIPT_DIR/plugin/"* "$PLUGIN_DIR/"
fi

# 5. Enable plugins in Omarchy
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin enable voice.orb 2>/dev/null || true
  omarchy plugin enable voice.indicator 2>/dev/null || true
fi

# 6. Setup API Key configuration if not existing
if [ ! -f "$CONFIG_DIR/env" ]; then
  if [ -f "$SCRIPT_DIR/env.example" ]; then
    cp "$SCRIPT_DIR/env.example" "$CONFIG_DIR/env"
  else
    echo "GEMINI_API_KEY=" > "$CONFIG_DIR/env"
  fi
  chmod 600 "$CONFIG_DIR/env"
fi
ln -sf "$CONFIG_DIR/env" "$HOME/.config/linux-voice/env"

# 7. Check dependencies
echo ""
echo "Checking system dependencies:"
for dep in pw-record wtype wl-copy notify-send python3; do
  if command -v "$dep" >/dev/null 2>&1; then
    echo "  [OK] $dep is installed"
  else
    echo "  [WARNING] $dep is missing (please install via pacman/yay)"
  fi
done

echo ""
echo "Installation complete!"
echo "Binaries: $BIN_DIR/linux-voice, $BIN_DIR/omarchy-dictate"
echo "Config:   $CONFIG_DIR/env"
echo "Hotkey:   SUPER + H (listening toggle)"
echo "Stop key: ENTER (stops and types directly into active window)"
echo "Cancel:   ESCAPE (cancels without typing)"
echo "========================================="
