#!/usr/bin/env bash
# Installer: Python venv + Playwright + Chromium (linux-x64).
# Works offline when ./wheels and ./browser/*.zip are present, otherwise
# falls back to downloading from PyPI / Playwright's CDN.
# Run on the target machine:
#     bash install_remote.sh
set -euo pipefail
cd "$(dirname "$0")"
BASE="$(pwd)"

PYBIN="$(command -v python3 || true)"
if [ -z "$PYBIN" ]; then
    echo "ERROR: python3 not found"; exit 1
fi
echo "Using: $PYBIN ($($PYBIN --version 2>&1))"

echo "[1/4] Creating python venv..."
"$PYBIN" -m venv plenv
[ -x ./plenv/bin/python ] || { echo "ERROR: venv not created"; exit 1; }

echo "[2/4] Installing playwright..."
if [ -f ./wheels/playwright-*.whl ]; then
    PIP_NO_INDEX=1 ./plenv/bin/python -m pip install --find-links ./wheels playwright
else
    ./plenv/bin/python -m pip install -r ./requirements.txt
fi

echo "[3/4] Installing Chromium..."
mkdir -p "$BASE/ms-playwright"
if [ -f ./browser/chrome-linux64.zip ]; then
    ./plenv/bin/python - "$BASE" <<'PY'
import os
import sys
import zipfile

base = os.path.join(sys.argv[1], "ms-playwright")
jobs = [
    ("browser/chrome-linux64.zip",                "chromium-1243"),
    ("browser/chrome-headless-shell-linux64.zip", "chromium_headless_shell-1243"),
]
for zfile, dest in jobs:
    if not os.path.exists(zfile):
        continue
    out = os.path.join(base, dest)
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(zfile) as zf:
        zf.extractall(out)
    print("   extracted", zfile, "->", out)
PY
    chmod +x "$BASE"/ms-playwright/*/chrome-linux*/chrome \
             "$BASE"/ms-playwright/*/chrome-linux*/chrome_crashpad_handler \
             "$BASE"/ms-playwright/*/chrome-headless-shell-linux*/chrome-headless-shell 2>/dev/null || true
else
    PLAYWRIGHT_BROWSERS_PATH="$BASE/ms-playwright" \
        ./plenv/bin/python -m playwright install chromium
fi

echo "[4/4] Verifying install..."
PLAYWRIGHT_BROWSERS_PATH="$BASE/ms-playwright" \
    ./plenv/bin/python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"

echo
echo "INSTALL_OK"
echo "Run login:  ./plenv/bin/python wifi_login.py --code YOUR_CODE"
echo "(or: WIFI_CODE=... ./plenv/bin/python wifi_login.py)"
