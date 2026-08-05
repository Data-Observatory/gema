#!/usr/bin/env bash
# Build a distributable .dmg from the PyInstaller macOS .app bundle.
# Run on macOS, from the repo root, after `make build-visor` has produced
# dist/Visor.app. Uses hdiutil (built into every macOS runner/machine) —
# no extra dependency. See visor/BUILD.md.
set -euo pipefail

APP_PATH="dist/Visor.app"
DMG_PATH="dist/Visor.dmg"

if [ ! -d "$APP_PATH" ]; then
  echo "error: $APP_PATH not found — run 'make build-visor' on macOS first" >&2
  exit 1
fi

rm -f "$DMG_PATH"
hdiutil create -volname "Visor" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
echo "Built $DMG_PATH"
