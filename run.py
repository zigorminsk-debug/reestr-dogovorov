from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from waitress import serve

from reestr import __version__, create_app
from reestr.db import default_data_dir


def load_settings() -> dict:
    settings = {"host": "0.0.0.0", "port": 8080}
    config_path = default_data_dir() / "server.json"
    if config_path.exists():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            settings.update({key: saved[key] for key in settings if key in saved})
        except (OSError, ValueError, TypeError):
            pass
    settings["host"] = os.environ.get("REESTR_HOST", settings["host"])
    settings["port"] = int(os.environ.get("REESTR_PORT", settings["port"]))
    return settings


def open_application(url: str) -> None:
    if sys.platform == "win32":
        candidates = []
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.extend(
                    [
                        Path(root) / "Microsoft/Edge/Application/msedge.exe",
                        Path(root) / "Google/Chrome/Application/chrome.exe",
                    ]
                )
        for browser in candidates:
            if browser.exists():
                subprocess.Popen([str(browser), f"--app={url}"], close_fds=True)
                return
    webbrowser.open(url)


def main() -> None:
    multiprocessing.freeze_support()
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Реестр договоров — сетевой сервер и HTML-интерфейс")
    parser.add_argument("--serve", action="store_true", help="запустить только серверную часть")
    parser.add_argument("--launch", action="store_true", help="открыть окно приложения")
    parser.add_argument("--host", default=settings["host"])
    parser.add_argument("--port", type=int, default=settings["port"])
    parser.add_argument("--url", default=os.environ.get("REESTR_URL"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    url = args.url or f"http://127.0.0.1:{args.port}/"
    if args.launch:
        open_application(url)
        return

    app = create_app()
    if not args.serve and not args.no_browser:
        threading.Timer(1.2, open_application, args=(url,)).start()
    app.logger.info("Запуск сервера: http://%s:%s, база: %s", args.host, args.port, app.config["DATABASE"])
    serve(
        app,
        host=args.host,
        port=args.port,
        threads=16,
        channel_timeout=120,
        max_request_body_size=16 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
