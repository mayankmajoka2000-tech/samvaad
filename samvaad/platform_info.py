"""What kind of laptop Samvaad is running on, so it can pick the fastest engines.

* Snapdragon PC (Windows on Arm): Whisper and Qwen3 on the Hexagon NPU.
* Any other Windows, Mac or Linux laptop: Whisper on the CPU (or an NVIDIA GPU) with
  faster-whisper, and Qwen3 through Ollama (Apple GPU on Macs, NVIDIA/AMD GPU or CPU elsewhere).
"""

from __future__ import annotations

import functools
import os
import platform
import subprocess
import sys


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return out.stdout.strip()
    except Exception:
        return ""


@functools.lru_cache(maxsize=1)
def chip_name() -> str:
    """A human-readable processor name, e.g. 'Apple M2', 'Snapdragon X Elite', 'Intel Core i5-1235U'."""
    system = platform.system()
    name = ""
    if system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    elif system == "Windows":
        name = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
    elif system == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith(("model name", "hardware")):
                        name = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
    return " ".join((name or platform.processor() or platform.machine() or "unknown").split())


def os_name() -> str:
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(platform.system(), platform.system())


def arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("amd64", "x86_64"):
        return "x64"
    return machine or "unknown"


def is_snapdragon_pc() -> bool:
    """Windows on Arm, where the Hexagon NPU path is available."""
    if os.environ.get("SAMVAAD_FORCE_SNAPDRAGON") == "1":
        return True
    return platform.system() == "Windows" and arch() == "arm64"


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and arch() == "arm64"


def describe() -> dict:
    return {
        "os": os_name(),
        "arch": arch(),
        "chip": chip_name(),
        "snapdragon": is_snapdragon_pc(),
        "apple_silicon": is_apple_silicon(),
        "python": sys.version.split()[0],
    }


def translator_hint(ollama_model: str) -> str:
    """How to start the translator on this kind of laptop (HTML for the interface banner)."""
    if is_snapdragon_pc():
        return ("The translator is not running. Open a new PowerShell window and run <code>geniex serve</code>, "
                "then keep it open (README, Snapdragon step 4). Ollama also works.")
    if platform.system() == "Darwin":
        start = "Open the <b>Ollama</b> app (Applications folder)"
    elif platform.system() == "Windows":
        start = "Open <b>Ollama</b> from the Start menu"
    else:
        start = "Run <code>ollama serve</code> in a terminal"
    return (f"The translator is not running. {start}, then run <code>ollama pull {ollama_model}</code> once. "
            "Or simply run the setup script again.")


def setup_command() -> str:
    return r"<code>.\setup.ps1</code>" if platform.system() == "Windows" else "<code>bash setup.sh</code>"


def run_command() -> str:
    return r"<code>.\run.ps1</code>" if platform.system() == "Windows" else "<code>bash run.sh</code>"
