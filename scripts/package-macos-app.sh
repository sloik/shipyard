#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/package-macos-app.sh [--skip-build] [--binary PATH] [--app PATH]

Packages the Wails v3 Shipyard desktop binary into a standard macOS .app bundle.
Default output: bin/Shipyard.app
USAGE
}

skip_build=0
binary_path="./bin/shipyard"
app_path="./bin/Shipyard.app"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build)
      skip_build=1
      shift
      ;;
    --binary)
      binary_path="${2:?missing --binary path}"
      shift 2
      ;;
    --app)
      app_path="${2:?missing --app path}"
      shift 2
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
  echo "macOS .app packaging must run on macOS because the desktop binary uses native Wails runtime support." >&2
  exit 1
fi

if [[ "$skip_build" -eq 0 ]]; then
  command -v wails3 >/dev/null || { echo "wails3 is required unless --skip-build is used." >&2; exit 1; }
  wails3 task build
fi

if [[ ! -x "$binary_path" ]]; then
  echo "Shipyard desktop binary is not executable: $binary_path" >&2
  echo "Run 'wails3 task build' first, or omit --skip-build." >&2
  exit 1
fi

bundle_name="${SHIPYARD_BUNDLE_NAME:-Shipyard}"
bundle_id="${SHIPYARD_BUNDLE_ID:-com.sloik.shipyard}"
version="${SHIPYARD_VERSION:-0.0.0-dev}"
build_number="${SHIPYARD_BUILD:-0}"
macos_min="${SHIPYARD_MACOS_MIN:-12.0}"
app_parent="$(dirname "$app_path")"
contents="$app_path/Contents"

mkdir -p "$app_parent"
rm -rf "$app_path"
mkdir -p "$contents/MacOS" "$contents/Resources"

cp "$binary_path" "$contents/MacOS/shipyard"
chmod 755 "$contents/MacOS/shipyard"
printf 'APPL????' > "$contents/PkgInfo"

cat > "$contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>shipyard</string>
  <key>CFBundleIdentifier</key>
  <string>$bundle_id</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$bundle_name</string>
  <key>CFBundleDisplayName</key>
  <string>$bundle_name</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$version</string>
  <key>CFBundleVersion</key>
  <string>$build_number</string>
  <key>LSMinimumSystemVersion</key>
  <string>$macos_min</string>
  <key>LSApplicationCategoryType</key>
  <string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

echo "Packaged macOS app: $app_path"
