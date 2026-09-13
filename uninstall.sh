#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling linux-voice..."

rm -rf "$HOME/.local/share/linux-voice"
rm -f "$HOME/.local/share/omarchy-dictate"
rm -f "$HOME/.local/bin/linux-voice"
rm -f "$HOME/.local/bin/omarchy-dictate"

echo "linux-voice uninstalled successfully."
echo "(Note: ~/.config/omarchy-dictate/env was preserved in case you re-install)"
