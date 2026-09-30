"""Run Samvaad: ``python -m samvaad [--lan] [--port 8765] [--asr qnn|transformers|mock]``."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import webbrowser

import uvicorn

from . import __version__, config
from .server import create_app


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(prog="samvaad", description="Offline AI interpreter for Snapdragon PCs.")
    parser.add_argument("--config", help="Path to config.toml (default: ./config.toml)")
    parser.add_argument("--host", help="Address to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Port (default 8765)")
    parser.add_argument("--lan", action="store_true", help="Also listen on the local network so Beacon can connect")
    parser.add_argument("--asr", choices=["qnn", "transformers", "mock"], help="Speech engine override")
    parser.add_argument("--llm", choices=["openai", "mock"], help="Language model override")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    cfg = config.load(args.config)
    if args.asr:
        cfg["asr"]["engine"] = args.asr
    if args.llm:
        cfg["llm"]["engine"] = args.llm
    host = args.host or ("0.0.0.0" if args.lan else cfg["server"]["host"])
    port = args.port or int(cfg["server"]["port"])

    url = f"http://127.0.0.1:{port}"
    print(f"\n  Samvaad {__version__}")
    print(f"  Open {url} in Edge or Chrome")
    if host == "0.0.0.0":
        print(f"  Beacon address: http://{lan_ip()}:{port}  (enter this on the UNO Q)")
    print(f"  Speech engine: {cfg['asr']['engine']}   Language model: {cfg['llm']['model']} at {cfg['llm']['base_url']}\n")

    if cfg["server"].get("open_browser", True) and not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
