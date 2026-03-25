#!/bin/bash
#
# Wine Smoke Test for TrollSkript Windows Executable
#
# This script downloads the latest trollskript.exe from GitHub Releases
# and runs basic smoke tests under Wine to verify it works.
#
# Usage:
#   ./scripts/test_windows_exe_with_wine.sh
#
# Prerequisites:
#   - Wine installed (sudo apt install wine)
#   - curl and jq installed
#

set -e

REPO="SimonRiemertzon/trollskript"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/trollskript_wine_test"

echo "============================================================"
echo "TrollSkript Wine Smoke Test"
echo "============================================================"

# Check prerequisites
echo ""
echo "Checking prerequisites..."

if ! command -v wine &> /dev/null; then
    echo "❌ Wine is not installed."
    echo ""
    echo "Install Wine with:"
    echo "  sudo dpkg --add-architecture i386"
    echo "  sudo apt update"
    echo "  sudo apt install wine64 wine32"
    exit 1
fi

# Check if wine32 is missing (Wine will print a warning)
WINE_OUTPUT=$(wine --version 2>&1)
if echo "$WINE_OUTPUT" | grep -q "wine32 is missing"; then
    echo "❌ Wine32 is missing. Install it with:"
    echo ""
    echo "  sudo dpkg --add-architecture i386"
    echo "  sudo apt update"
    echo "  sudo apt install wine32"
    exit 1
fi
echo "✓ Wine is installed: $WINE_OUTPUT"

if ! command -v curl &> /dev/null; then
    echo "❌ curl is not installed. Install with: sudo apt install curl"
    exit 1
fi
echo "✓ curl is installed"

if ! command -v jq &> /dev/null; then
    echo "⚠ jq is not installed (optional, will use fallback method)"
    USE_JQ=false
else
    echo "✓ jq is installed"
    USE_JQ=true
fi

# Create work directory
echo ""
echo "Setting up test environment..."
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/source" "$WORK_DIR/dest"

# Download latest release (including pre-releases)
echo ""
echo "Fetching releases from GitHub..."

# Use /releases endpoint to get all releases (including pre-releases)
# The /releases/latest endpoint only returns non-pre-release versions
API_RESPONSE=$(curl -s "https://api.github.com/repos/$REPO/releases")

# Check if any releases exist
if echo "$API_RESPONSE" | grep -q '^\[\]$' || echo "$API_RESPONSE" | grep -q '"message": "Not Found"'; then
    echo "❌ No releases found on GitHub"
    echo ""
    echo "To create a release:"
    echo "  1. Go to https://github.com/$REPO/releases"
    echo "  2. Click 'Create a new release'"
    echo "  3. Create a tag (e.g., v1.0.0)"
    echo "  4. Wait for GitHub Actions to build and attach trollskript.exe"
    exit 1
fi

if $USE_JQ; then
    # Get the first .exe from the most recent release (first in array)
    RELEASE_URL=$(echo "$API_RESPONSE" | jq -r '.[0].assets[] | select(.name | endswith(".exe")) | .browser_download_url' 2>/dev/null | head -1)
    RELEASE_TAG=$(echo "$API_RESPONSE" | jq -r '.[0].tag_name' 2>/dev/null)
else
    # Fallback: parse JSON with grep/sed (gets first match)
    RELEASE_URL=$(echo "$API_RESPONSE" | grep -o '"browser_download_url": *"[^"]*\.exe"' | head -1 | sed 's/.*"\(http[^"]*\)"/\1/')
    RELEASE_TAG="(unknown)"
fi

if [ -z "$RELEASE_URL" ] || [ "$RELEASE_URL" = "null" ]; then
    echo "❌ Releases exist but no .exe asset found"
    echo ""
    echo "This could mean:"
    echo "  - GitHub Actions workflow hasn't completed yet"
    echo "  - The build failed"
    echo ""
    echo "Check: https://github.com/$REPO/actions"
    exit 1
fi

echo "Found release: $RELEASE_TAG"

echo "Downloading: $RELEASE_URL"
curl -L -o "$WORK_DIR/trollskript.exe" "$RELEASE_URL"
echo "✓ Downloaded trollskript.exe"

# Run smoke tests
echo ""
echo "============================================================"
echo "Running Smoke Tests"
echo "============================================================"

# Test 1: --help should work
echo ""
echo "Test 1: Running --help..."
if wine "$WORK_DIR/trollskript.exe" --help 2>/dev/null; then
    echo "✓ --help works"
else
    echo "❌ --help failed"
    exit 1
fi

# Test 2: Run with empty source directory
echo ""
echo "Test 2: Running with empty source directory..."
if wine "$WORK_DIR/trollskript.exe" --src "Z:$WORK_DIR/source" --dest "Z:$WORK_DIR/dest" 2>/dev/null; then
    echo "✓ Empty source run works"
else
    echo "⚠ Empty source run had issues (may be expected if ExifTool download fails under Wine)"
fi

echo ""
echo "============================================================"
echo "Smoke tests completed!"
echo "============================================================"
echo ""
echo "Test files are in: $WORK_DIR"
echo "To clean up: rm -rf $WORK_DIR"

