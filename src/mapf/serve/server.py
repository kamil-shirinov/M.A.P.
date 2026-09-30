"""The request boundary: what is allowed to reach the analysis, and from where.

BINDING TO LOOPBACK IS NOT THE CHECK. It stops a machine on the network reaching
the port and does nothing at all about a page already open in the visitor's own
browser. Two attacks get through it:

  DNS rebinding   an attacker's domain resolves to 127.0.0.1 after the page
                  loads, so the browser treats this server as same-origin and
                  sends requests with the attacker's `Host`.
  plain CSRF      any page can `POST` cross-origin without reading the reply,
                  which is enough when the side effect IS the point — and here
                  each request costs minutes of local inference and writes a
                  permanent journal entry.

So every request is checked twice. `Host` must name a loopback address this
server is actually bound to, which is what defeats rebinding: the attacker's
domain cannot appear there. `Origin`, when the browser sends one, must equal this
server's own origin, which is what defeats the cross-origin POST.

Serving the app and the endpoint from ONE server is what makes the second check
strict rather than advisory. With a separate API port, cross-origin would be the
normal case and `Origin` could only ever be a warning.

Stdlib `http.server` on purpose: no new dependency for a server that exists to
run on one machine for one person (CLAUDE.md §2.4).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import structlog

_logger = structlog.get_logger(__name__)

# The addresses a loopback server may legitimately be reached on. `localhost` is
# included because browsers resolve it to one of the other two, and excluding it
# would refuse the URL a person actually types.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

# Conservative on purpose: a ticker is at most five letters plus an optional class
# suffix. It is validated here as well as downstream because this string reaches a
# filesystem path and an HTTP query, and one check at the boundary is cheaper to
# reason about than trusting three layers to agree.
TICKER = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

MAX_BODY_BYTES = 4096


@dataclass
class Config:
    """What the handler needs, passed in rather than imported.

    `analyse` is a callable so the whole server can be exercised against a stub
    that yields recorded lines, with no model and no network (CLAUDE.md §6).
    """

    root: Path
    port: int
    analyse: Callable[[str, int], Iterator[dict[str, object]]]
    bound_hosts: frozenset[str] = field(default_factory=lambda: LOOPBACK_HOSTS)
    # Reads, not runs. A company page outside the corpus has no exported series and
    # no exported live runs newer than the last export, so the server answers both
    # from what this machine holds. Neither can start a run or write anything.
    prices: Callable[[str], dict[str, object]] | None = None
    live_runs: Callable[[str], list[dict[str, object]]] | None = None
    # The latest trade and whether the market is open (ADR 0039). A read like the
    # other two: it fetches for this machine and writes nothing.
    quote: Callable[[str], dict[str, object]] | None = None


def host_allowed(header: str | None, *, port: int, allowed: frozenset[str]) -> bool:
    """`Host` names a loopback address this server is bound to.

    A missing `Host` is refused rather than waved through: HTTP/1.1 requires it,
    and the only clients that omit it are not browsers.
    """
    if not header:
        return False
    name = header.rsplit(":", 1)[0] if _has_port(header) else header
    if name not in allowed:
        return False
    if _has_port(header):
        try:
            return int(header.rsplit(":", 1)[1]) == port
        except ValueError:
            return False
    # No port means the default one, which is never this server's.
    return False


def _has_port(header: str) -> bool:
    # `[::1]:8765` has a port; `[::1]` does not. Splitting on the last colon is
    # wrong for a bare IPv6 literal, which is why the bracket is checked first.
    tail = header.rsplit(":", 1)
    return len(tail) == 2 and not tail[1].endswith("]")


def origin_allowed(header: str | None, *, port: int, allowed: frozenset[str]) -> bool:
    """`Origin`, when sent, is this server's own.

    Absent is allowed: same-origin `GET`s and non-browser clients such as `curl`
    send none, and refusing those would break the app itself. The `Host` check is
    what covers that case — this one exists for the request that DOES carry an
    origin, which is every cross-origin POST a browser makes.

    `null` is refused explicitly. Sandboxed iframes and `file://` pages send it,
    and neither is this app.
    """
    if header is None:
        return True
    if header == "null":
        return False
    parsed = urlsplit(header)
    if parsed.scheme != "http":
        return False
    return parsed.hostname in {h.strip("[]") for h in allowed} and parsed.port == port


class ReadRefusedError(Exception):
    """A read endpoint could not answer, with a sentence the page can print."""


class Handler(BaseHTTPRequestHandler):
    """Routes five things and refuses everything else.

    `GET /health`, `GET /prices`, `GET /runs` and the static app are reads.
    `POST /analyse` is the only request that makes anything exist.
    """

    config: Config
    protocol_version = "HTTP/1.1"
    server_version = "mapf"
    # The default appends the Python version, which tells a scanner more than it
    # needs and says nothing a reader wants.
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        _logger.debug("serve_request", line=format % args)

    # -- the boundary ---------------------------------------------------------
    def _checked(self) -> bool:
        port = self.config.port
        allowed = self.config.bound_hosts
        if not host_allowed(self.headers.get("Host"), port=port, allowed=allowed):
            self._refuse(
                421,
                "host_not_loopback",
                "This server answers only on a loopback address it is bound to. "
                "A request naming any other host is refused before anything runs.",
            )
            return False
        if not origin_allowed(self.headers.get("Origin"), port=port, allowed=allowed):
            self._refuse(
                403,
                "cross_origin",
                "The app and this endpoint are served from one origin, so a request "
                "carrying a different one did not come from the app.",
            )
            return False
        return True

    def _refuse(self, status: int, kind: str, why: str) -> None:
        _logger.warning(
            "serve_refused",
            kind=kind,
            host=self.headers.get("Host"),
            origin=self.headers.get("Origin"),
        )
        self._send(
            status,
            "application/json; charset=utf-8",
            json.dumps({"refused": kind, "why": why}).encode(),
        )

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is meant to be embedded, cached or sniffed.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        if not self._checked():
            return
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
            return
        if path in ("/prices", "/runs", "/quote"):
            self._read(path, parse_qs(parts.query).get("ticker", [""])[0])
            return
        self._static(path)

    def _read(self, path: str, raw: str) -> None:
        """One company's price window, live runs or latest quote, as JSON.

        The ticker is checked with the same pattern `POST /analyse` uses, because it
        reaches a cache path and a provider query exactly as that one does.
        """
        ticker = raw.strip().upper()
        if not TICKER.match(ticker):
            self._refuse(400, "bad_ticker", f"{raw!r} is not a ticker this server will look up.")
            return
        reader = {
            "/prices": self.config.prices,
            "/runs": self.config.live_runs,
            "/quote": self.config.quote,
        }[path]
        if reader is None:
            self._refuse(404, "no_such_endpoint", "This server was started without that read.")
            return
        try:
            body = reader(ticker)
        except ReadRefusedError as refusal:
            self._refuse(502, "read_failed", str(refusal))
            return
        self._send(200, "application/json; charset=utf-8", json.dumps(body).encode())

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        if not self._checked():
            return
        if urlsplit(self.path).path != "/analyse":
            self._refuse(404, "no_such_endpoint", "This server exposes one endpoint.")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._refuse(400, "bad_length", "The request length could not be read.")
            return
        if length > MAX_BODY_BYTES:
            self._refuse(413, "body_too_large", "An analysis request is a ticker and a horizon.")
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            ticker = str(body["ticker"]).strip().upper()
            horizon = int(body.get("horizon_days", 5))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._refuse(400, "unreadable_request", 'Send {"ticker": "AAPL", "horizon_days": 5}.')
            return
        if not TICKER.match(ticker):
            self._refuse(400, "bad_ticker", f"{ticker!r} is not a ticker this server will look up.")
            return
        if horizon not in (5, 10, 21):
            self._refuse(
                400,
                "bad_horizon",
                "Five, ten or twenty-one sessions. Ten and twenty-one are uncalibrated "
                "and are marked as such.",
            )
            return
        self._stream(ticker, horizon)

    def _stream(self, ticker: str, horizon: int) -> None:
        """Newline-delimited JSON, flushed per line.

        Chunked rather than buffered because the point of the screen is watching it
        happen: a run takes minutes on this hardware, and a response that arrives
        complete would be a progress display with nothing to display.
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for line in self.config.analyse(ticker, horizon):
                self._chunk(json.dumps(line).encode() + b"\n")
        except Exception as error:  # noqa: BLE001 - the stream must end with a reason
            # The connection is already open with a 200, so a failure cannot become
            # a status code. It becomes a final line, which the page renders as the
            # absence it is rather than as a run that vanished.
            _logger.warning("serve_analysis_failed", ticker=ticker, error=str(error))
            self._chunk(
                json.dumps(
                    {"event": "failed", "why": str(error), "kind": type(error).__name__}
                ).encode()
                + b"\n"
            )
        self._chunk(b"")

    def _chunk(self, payload: bytes) -> None:
        self.wfile.write(f"{len(payload):X}\r\n".encode())
        self.wfile.write(payload + b"\r\n")
        self.wfile.flush()

    def _static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (self.config.root / name).resolve()
        root = self.config.root.resolve()
        # Traversal is refused by comparing resolved paths, not by inspecting the
        # request for "..": encodings of that are endless and this comparison holds
        # whatever the request said.
        if not target.is_relative_to(root) or not target.is_file():
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        self._send(
            200, CONTENT_TYPES.get(target.suffix, "application/octet-stream"), target.read_bytes()
        )


def build(config: Config) -> ThreadingHTTPServer:
    """A server bound to loopback, with the handler's config attached.

    Threading so a page can still load its stylesheet while an analysis streams;
    a single-threaded server would make the app appear to hang for the whole run.
    """
    handler = type("BoundHandler", (Handler,), {"config": config})
    return ThreadingHTTPServer(("127.0.0.1", config.port), handler)
