#!/usr/bin/env bash
# install-plugin.sh – Install the AI Video Agent CEP panel into Premiere Pro
set -euo pipefail

PLUGIN_SRC="$(cd "$(dirname "$0")/premiere-plugin" && pwd)"
BUNDLE_ID="com.videoagent.plugin"

# ── Detect OS ────────────────────────────────────────────────────────────────
case "$(uname -s)" in
  Darwin)
    CEP_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions"
    ;;
  Linux)
    CEP_DIR="$HOME/.config/Adobe/CEP/extensions"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    CEP_DIR="$APPDATA/Adobe/CEP/extensions"
    ;;
  *)
    echo "Unsupported OS: $(uname -s)"
    exit 1
    ;;
esac

DEST="$CEP_DIR/$BUNDLE_ID"

echo "────────────────────────────────────────────────"
echo "  AI Video Agent – Premiere Pro Plugin Installer"
echo "────────────────────────────────────────────────"
echo
echo "Source : $PLUGIN_SRC"
echo "Dest   : $DEST"
echo

# ── Check source ─────────────────────────────────────────────────────────────
if [ ! -f "$PLUGIN_SRC/CSXS/manifest.xml" ]; then
  echo "ERROR: premiere-plugin/CSXS/manifest.xml not found."
  echo "Make sure you're running this script from the Agent-1 directory."
  exit 1
fi

if [ ! -f "$PLUGIN_SRC/CSInterface.js" ]; then
  echo "ERROR: premiere-plugin/CSInterface.js not found."
  echo "Run: curl -o premiere-plugin/CSInterface.js https://raw.githubusercontent.com/Adobe-CEP/CEP-Resources/master/CEP_11.x/CSInterface.js"
  exit 1
fi

# ── Warn if Premiere is running ───────────────────────────────────────────────
if pgrep -x "Adobe Premiere Pro" > /dev/null 2>&1; then
  echo "⚠  Premiere Pro is currently running."
  echo "   You must restart it after installation for the panel to appear."
  echo
fi

# ── Install ───────────────────────────────────────────────────────────────────
mkdir -p "$CEP_DIR"

if [ -d "$DEST" ]; then
  echo "Removing existing installation…"
  rm -rf "$DEST"
fi

echo "Copying plugin files…"
cp -R "$PLUGIN_SRC" "$DEST"

echo "Done. Plugin installed to:"
echo "  $DEST"
echo

# ── Enable unsigned extensions (required for development) ────────────────────
echo "Enabling unsigned CEP extensions (required for development)…"

if [[ "$(uname -s)" == "Darwin" ]]; then
  # Try each Premiere version key (CC 2019 = v9, up to v12)
  for ver in 9 10 11 12; do
    defaults write com.adobe.CSXS.$ver PlayerDebugMode 1 2>/dev/null || true
  done
  echo "  PlayerDebugMode set for CSXS versions 9–12."
  echo
  echo "  If Premiere still won't show the panel, also run:"
  echo "    defaults write com.adobe.CSXS.11 PlayerDebugMode 1"
  echo "  (replace 11 with the version number matching your Premiere install)"
fi

echo
echo "────────────────────────────────────────────────"
echo "  Installation complete!"
echo
echo "  Next steps:"
echo "  1. Start (or restart) Adobe Premiere Pro"
echo "  2. Go to  Window → Extensions → AI Video Agent"
echo "  3. Start the agent server:  python server.py"
echo "  4. The panel status dot will turn green when connected"
echo "────────────────────────────────────────────────"
