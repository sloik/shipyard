#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/sign-macos-app.sh [--app PATH] [--notarize]

Signs bin/Shipyard.app for macOS distribution. Set signing prerequisites with:
  SHIPYARD_MACOS_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"
  SHIPYARD_MACOS_NOTARY_PROFILE="notarytool-keychain-profile"  # required for --notarize

SIGN_IDENTITY and KEYCHAIN_PROFILE are also accepted for compatibility with
Wails v3 Taskfile variable names.
USAGE
}

app_path="./bin/Shipyard.app"
notarize=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app)
      app_path="${2:?missing --app path}"
      shift 2
      ;;
    --notarize)
      notarize=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS signing and notarization must run on macOS." >&2
  exit 1
fi

command -v codesign >/dev/null || { echo "codesign is required for macOS signing." >&2; exit 1; }

sign_identity="${SHIPYARD_MACOS_SIGN_IDENTITY:-${SIGN_IDENTITY:-}}"
if [[ -z "$sign_identity" ]]; then
  echo "missing macOS signing identity." >&2
  echo "Set SHIPYARD_MACOS_SIGN_IDENTITY or SIGN_IDENTITY to a Developer ID Application identity." >&2
  echo "List available identities with: security find-identity -v -p codesigning" >&2
  exit 2
fi

if [[ ! -d "$app_path" ]]; then
  echo "app bundle not found: $app_path" >&2
  echo "Run 'wails3 package GOOS=darwin' first." >&2
  exit 1
fi

entitlements="${SHIPYARD_MACOS_ENTITLEMENTS:-${ENTITLEMENTS:-build/darwin/entitlements.plist}}"
codesign_args=(--force --deep --options runtime --timestamp --sign "$sign_identity")
if [[ -f "$entitlements" ]]; then
  codesign_args+=(--entitlements "$entitlements")
fi

codesign "${codesign_args[@]}" "$app_path"
codesign --verify --deep --strict --verbose=2 "$app_path"

if [[ "$notarize" -eq 1 ]]; then
  command -v xcrun >/dev/null || { echo "xcrun is required for notarization." >&2; exit 1; }
  keychain_profile="${SHIPYARD_MACOS_NOTARY_PROFILE:-${KEYCHAIN_PROFILE:-}}"
  if [[ -z "$keychain_profile" ]]; then
    echo "missing notarization keychain profile." >&2
    echo "Set SHIPYARD_MACOS_NOTARY_PROFILE or KEYCHAIN_PROFILE after storing credentials with xcrun notarytool." >&2
    exit 2
  fi

  notary_zip="${app_path%.app}-notary.zip"
  rm -f "$notary_zip"
  ditto -c -k --keepParent "$app_path" "$notary_zip"
  xcrun notarytool submit "$notary_zip" --keychain-profile "$keychain_profile" --wait
  xcrun stapler staple "$app_path"
  spctl --assess --type execute --verbose "$app_path"
fi

echo "Signed macOS app: $app_path"
