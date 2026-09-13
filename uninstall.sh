#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling linux-voice..."

rm -rf "$HOME/.local/share/linux-voice"
rm -f "$HOME/.local/share/omarchy-dictate"
rm -f "$HOME/.local/bin/linux-voice"
rm -f "$HOME/.local/bin/omarchy-dictate"

# Disable and remove plugins
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable voice.orb 2>/dev/null || true
  omarchy plugin disable voice.indicator 2>/dev/null || true
fi
rm -rf "$HOME/.config/omarchy/plugins/voice.orb"
rm -rf "$HOME/.config/omarchy/plugins/voice.indicator"

echo "linux-voice uninstalled successfully."
echo "(Note: ~/.config/omarchy-dictate/env was preserved in case you re-install)"
