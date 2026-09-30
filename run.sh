#!/usr/bin/env bash
# Start Samvaad on a Mac or Linux laptop (and Ollama, if it is not running) and open it in the browser.
#
#   bash run.sh           # this laptop only
#   bash run.sh --lan     # also reachable on Wi-Fi, for the Beacon
#   bash run.sh --mock    # try the interface without models
#
# Any other option is passed to `python -m samvaad` (see --help).

set -eo pipefail
cd "$(dirname "$0")"

VPY=".venv/bin/python"
if [ ! -x "$VPY" ]; then
  echo "Samvaad is not set up yet. Run:  bash setup.sh"
  exit 1
fi

ollama_up() { curl -s -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; }
case " $* " in *" --mock "*) MOCK=1 ;; *) MOCK=0 ;; esac

if [ "$MOCK" = "0" ] && ! ollama_up; then
  if [ "$(uname -s)" = "Darwin" ] && { [ -d /Applications/Ollama.app ] || [ -d "$HOME/Applications/Ollama.app" ]; }; then
    echo "Starting Ollama..."
    open -g -a Ollama 2>/dev/null || open -g "$HOME/Applications/Ollama.app" 2>/dev/null || true
  elif command -v ollama >/dev/null 2>&1; then
    echo "Starting Ollama..."
    nohup ollama serve >/tmp/samvaad-ollama.log 2>&1 &
  else
    echo "Ollama is not installed, so translation is off. Run: bash setup.sh"
  fi
fi

exec "$VPY" -m samvaad "$@"
