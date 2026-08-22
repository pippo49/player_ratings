"""Small stdlib HTTP server for the ratings web app.

Deliberately dependency-free: the CLI already pulls in requests and
BeautifulSoup, and a personal LAN app does not need a web framework on top.

    python -m webapp.server            # http://0.0.0.0:8000
    python -m webapp.server --port 9000
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cache import load_matches, merge_matches, save_matches
from scraper import scrape_all_divisions
from webapp.api import build_payload
from webapp.export import export

STATIC_DIR = Path(__file__).parent / "static"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}


class RatingsStore:
    """Holds the current match list and its computed payload.

    The payload is expensive enough (an iterative ELO convergence over the
    whole season) that it is computed once and reused until an update or
    refresh replaces the underlying matches.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._matches = load_matches() or []
        self._payload: dict | None = None

    def payload(self) -> dict:
        with self._lock:
            if self._payload is None:
                self._payload = build_payload(self._matches)
            return self._payload

    def replace(self, matches: list) -> None:
        with self._lock:
            self._matches = matches
            self._payload = None

    @property
    def matches(self) -> list:
        with self._lock:
            return list(self._matches)


class UpdateJob:
    """Tracks a background scrape so the phone gets progress, not a hung tab."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.log: list[str] = []
        self.error: str | None = None
        self.added: int | None = None
        self.finished_at: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "log": list(self.log),
                "error": self.error,
                "added": self.added,
                "finished_at": self.finished_at,
            }

    def start(self, store: RatingsStore, mode: str) -> bool:
        """Kick off a scrape. Returns False if one is already in flight."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.log = []
            self.error = None
            self.added = None
            self.finished_at = None
        threading.Thread(target=self._run, args=(store, mode), daemon=True).start()
        return True

    def _say(self, message: str) -> None:
        with self._lock:
            self.log.append(message)

    def _run(self, store: RatingsStore, mode: str) -> None:
        try:
            existing = store.matches
            full = mode == "refresh" or not existing
            self._say(
                "Re-downloading every division…" if full
                else "Checking all divisions for new results…"
            )
            scraped = self._scrape()

            if full:
                matches, added = scraped, len(scraped)
            else:
                matches, added = merge_matches(existing, scraped)

            save_matches(matches)
            self._say(f"Recalculating ratings over {len(matches)} matches…")
            store.replace(matches)
            store.payload()  # warm the cache before the client asks for it
            export(verbose=False)
            self._say("Static snapshot updated — commit it to publish.")

            with self._lock:
                self.added = added
            self._say(
                f"{added} new match(es) added." if not full
                else f"{added} match(es) downloaded."
            )
        except Exception as exc:  # surfaced in the UI rather than the console
            with self._lock:
                self.error = f"{type(exc).__name__}: {exc}"
            self._say("Update failed.")
        finally:
            with self._lock:
                self.running = False
                self.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _scrape(self) -> list:
        """Scrape every division, reporting progress one division at a time."""
        def on_division(div: int, total: int, parsed: int | None, error: str | None) -> None:
            if error:
                brief = error if len(error) <= 90 else f"{error[:87]}…"
                self._say(f"Division {div} of {total} failed — {brief}")
            else:
                self._say(f"Division {div} of {total} — {parsed} matches")

        matches = scrape_all_divisions(verbose=False, progress=on_division)
        if not matches:
            raise RuntimeError("No matches could be fetched — check your connection.")
        return matches


class Handler(BaseHTTPRequestHandler):
    server_version = "RatingsApp/1.0"
    store: RatingsStore
    job: UpdateJob

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        return

    # ── helpers ──

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data).encode(), CONTENT_TYPES[".json"])

    def _static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR.resolve() not in path.parents:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), ctype)

    # ── routes ──

    def do_GET(self) -> None:
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            self._static("index.html")
        elif route == "/ratings.json":
            # Served live, overriding the committed snapshot of the same name,
            # so a running server always shows the freshest ratings.
            self._json({**self.store.payload(), "live": True})
        elif route == "/api/update":
            self._json(self.job.snapshot())
        elif route.count("/") == 1:
            self._static(route.lstrip("/"))
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route != "/api/update":
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        mode = "refresh" if body.get("mode") == "refresh" else "update"

        if not self.job.start(self.store, mode):
            self._json({"started": False, **self.job.snapshot()}, HTTPStatus.CONFLICT)
            return
        self._json({"started": True, **self.job.snapshot()}, HTTPStatus.ACCEPTED)


def _lan_address() -> str:
    """Best-effort local network IP, so the phone knows where to point."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # no packets sent; just picks the route
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    Handler.store = RatingsStore()
    Handler.job = UpdateJob()

    matches = Handler.store.matches
    if matches:
        print(f"Loaded {len(matches)} matches from cache.")
    else:
        print("No cached data yet — use the Update button in the app to fetch results.")

    httpd = ThreadingHTTPServer((host, port), Handler)
    print("\nCentral League London ELO Ratings — web app")
    print(f"  On this machine : http://localhost:{port}")
    if host == "0.0.0.0":
        print(f"  On your phone   : http://{_lan_address()}:{port}  (same Wi-Fi)")
    print("\nCtrl-C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the ratings web app")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Interface to bind (default 0.0.0.0, all interfaces)")
    serve(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
