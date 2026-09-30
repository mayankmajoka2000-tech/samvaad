#!/usr/bin/env bash
# One-time setup for Samvaad on a Mac (Apple Silicon or Intel) or a Linux laptop.
#
#   bash setup.sh                    # everything: Python, Whisper, Ollama + Qwen3, a quick test
#   bash setup.sh --whisper=base     # smaller, faster speech model (small is more accurate)
#   bash setup.sh --no-translator    # skip Ollama and Qwen3 (about 2.5 GB)
#
# Needs an internet connection once. After this, Samvaad works offline.
# On Windows use setup.ps1 instead.

set -eo pipefail
cd "$(dirname "$0")"

WHISPER="${SAMVAAD_WHISPER:-small}"
OLLAMA_MODEL="${SAMVAAD_OLLAMA_MODEL:-qwen3:4b-instruct-2507-q4_K_M}"
TRANSLATOR=1
for arg in "$@"; do
  case "$arg" in
    --whisper=*) WHISPER="${arg#*=}" ;;
    --no-translator) TRANSLATOR=0 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done

step() { printf '\n\033[36m[%s/7] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '      \033[32m%s\033[0m\n' "$1"; }
warn() { printf '      \033[33m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$1"; exit 1; }

# ------------------------------------------------------------------ 1
step 1 "Checking this laptop"
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin) CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo Mac)" ;;
  Linux)  CHIP="$(grep -m1 -i 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')" ;;
  *)      fail "This script is for macOS and Linux. On Windows, run setup.ps1 in PowerShell." ;;
esac
echo "      ${CHIP:-unknown processor} ($OS, $ARCH)"
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
  ok "Apple Silicon: Qwen3 will run on the Mac's GPU"
fi
command -v curl >/dev/null 2>&1 || fail "curl is needed. Install it and run setup.sh again."

# ------------------------------------------------------------------ 2
step 2 "Finding Python 3.11 to 3.13"
PY=""
for c in python3.12 python3.13 python3.11 python3; do
  p="$(command -v "$c" 2>/dev/null || true)"
  [ -n "$p" ] || continue
  # On a Mac without developer tools, /usr/bin/python3 only opens an install dialog.
  if [ "$OS" = "Darwin" ] && [ "$p" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
  if "$p" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' >/dev/null 2>&1; then
    PY="$p"; break
  fi
done

use_uv() {
  # uv installs its own Python 3.12 in your home folder: no admin rights, no Homebrew needed.
  UV="$(command -v uv 2>/dev/null || true)"
  if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; fi
  if [ -z "$UV" ] && [ -x "$HOME/.cargo/bin/uv" ]; then UV="$HOME/.cargo/bin/uv"; fi
  if [ -z "$UV" ]; then
    echo "      Installing uv (a Python installer) into your home folder..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null
    UV="$HOME/.local/bin/uv"
    [ -x "$UV" ] || UV="$HOME/.cargo/bin/uv"
  fi
  [ -x "$UV" ] || fail "Could not install uv. Install Python 3.12 from python.org and run setup.sh again."
  "$UV" venv --python 3.12 --seed .venv >/dev/null
}

VPY=".venv/bin/python"
if [ ! -x "$VPY" ]; then
  if [ -n "$PY" ] && "$PY" -m venv .venv >/dev/null 2>&1 && [ -x "$VPY" ]; then
    ok "Python: $PY"
  else
    rm -rf .venv
    if [ -n "$PY" ]; then
      warn "$PY cannot create a virtual environment; using uv instead."
    else
      echo "      No suitable Python found; getting Python 3.12 with uv."
    fi
    use_uv
    ok "Python 3.12 from uv"
  fi
else
  ok "Using the existing .venv"
fi

# ------------------------------------------------------------------ 3
step 3 "Installing packages into .venv"
"$VPY" -m pip install --upgrade pip --quiet
"$VPY" -m pip install -r requirements.txt --quiet || fail "Installing packages failed. Check the internet connection and run setup.sh again."
ok "Packages installed"

# ------------------------------------------------------------------ 4
step 4 "Downloading the Whisper speech model ($WHISPER)"
"$VPY" - "$WHISPER" <<'PYEOF'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
print(f"      Whisper-{sys.argv[1]} is ready and cached for offline use")
PYEOF

# ------------------------------------------------------------------ 5
ollama_up() { curl -s -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; }
find_ollama() {
  for p in "$(command -v ollama 2>/dev/null || true)" \
           "/Applications/Ollama.app/Contents/Resources/ollama" \
           "$HOME/Applications/Ollama.app/Contents/Resources/ollama"; do
    if [ -n "$p" ] && [ -x "$p" ]; then echo "$p"; return 0; fi
  done
  return 1
}
start_ollama() {
  ollama_up && return 0
  if [ "$OS" = "Darwin" ]; then
    open -g -a Ollama 2>/dev/null || open -g "$HOME/Applications/Ollama.app" 2>/dev/null || true
  else
    nohup "$OLLAMA" serve >/tmp/samvaad-ollama.log 2>&1 &
  fi
  for _ in $(seq 1 60); do ollama_up && return 0; sleep 1; done
  return 1
}

step 5 "Translator: Qwen3-4B with Ollama"
if [ "$TRANSLATOR" = "0" ]; then
  warn "Skipped (--no-translator). Samvaad will show the original text until a translator runs."
else
  OLLAMA="$(find_ollama || true)"
  if [ -z "$OLLAMA" ]; then
    if [ "$OS" = "Darwin" ]; then
      echo "      Installing the Ollama app..."
      TMPZIP="$(mktemp -d)/Ollama-darwin.zip"
      curl -fL --progress-bar -o "$TMPZIP" https://ollama.com/download/Ollama-darwin.zip
      DEST="/Applications"; [ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
      ditto -x -k "$TMPZIP" "$DEST"
      ok "Installed Ollama in $DEST"
    else
      echo "      Installing Ollama (it may ask for your password)..."
      command -v zstd >/dev/null 2>&1 || warn "If the install fails, install zstd first (e.g. sudo apt install zstd)."
      curl -fsSL https://ollama.com/install.sh | sh
    fi
    OLLAMA="$(find_ollama || true)"
  fi
  [ -n "$OLLAMA" ] || fail "Ollama did not install. Get it from https://ollama.com/download and run setup.sh again."
  ok "Ollama: $OLLAMA"
  start_ollama || fail "Ollama did not start. Open the Ollama app (or run 'ollama serve'), then run setup.sh again."
  echo "      Downloading $OLLAMA_MODEL (about 2.5 GB, first time only)..."
  "$OLLAMA" pull "$OLLAMA_MODEL"
  ok "Translator ready"
fi

# ------------------------------------------------------------------ 6
step 6 "Sample clip and settings"
mkdir -p samples
if [ ! -f samples/fox.wav ]; then
  if curl -fsSL -o samples/fox.wav https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/hf_whisper_asr_shared/v1/audio/fox.wav; then
    ok "Downloaded samples/fox.wav"
  else
    rm -f samples/fox.wav; warn "Could not download the sample clip; skipping the speech test."
  fi
fi
if [ ! -f config.toml ]; then
  sed "s/^cpu_model_size = \"small\"/cpu_model_size = \"$WHISPER\"/" config.example.toml > config.toml
  ok "Created config.toml"
else
  ok "config.toml already exists (left unchanged)"
fi

# ------------------------------------------------------------------ 7
step 7 "Quick test on this laptop"
if [ -f samples/fox.wav ]; then
  if [ "$TRANSLATOR" = "0" ]; then "$VPY" tools/benchmark.py --runs 2 --skip-llm || warn "The test failed; see README > Troubleshooting."
  else "$VPY" tools/benchmark.py --runs 2 || warn "The test failed; see README > Troubleshooting."; fi
else
  warn "Skipped (no sample clip)."
fi

printf '\n\033[32mSetup complete. Start Samvaad with:  bash run.sh\033[0m\n'
printf '\033[32mWith Beacon on the same Wi-Fi:        bash run.sh --lan\033[0m\n\n'
