"""The local analysis server — ADR 0036 §3.

Almost all of this is about what gets REFUSED. Binding to loopback is not a
security boundary: DNS rebinding reaches it from an attacker's domain, and a
plain cross-origin POST reaches it from any page the visitor has open. Each
request costs minutes of local inference and writes a permanent journal entry, so
the side effect is the attack.

No model, no network: `analyse` is a callable and these tests pass a stub.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from mapf.serve.server import Config, build, host_allowed, origin_allowed

PORT = 8791


def _raw(request_line: str, *, port: int = 8791, host: str | None = None) -> str:
    """One request, exactly as written, with no client between it and the server."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    head = f"{request_line}\r\nHost: {host or f'127.0.0.1:{port}'}\r\nConnection: close\r\n\r\n"
    sock.sendall(head.encode())
    chunks: list[bytes] = []
    while chunk := sock.recv(4096):
        chunks.append(chunk)
    sock.close()
    return b"".join(chunks).decode(errors="replace")


def _lines(_ticker: str, horizon: int) -> Iterator[dict[str, object]]:
    yield {"event": "progress", "stage": "filing", "detail": "found"}
    yield {"event": "result", "horizon_days": horizon, "marking": "settled"}


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, httpx.Client]]:
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not served", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    server = build(Config(root=tmp_path, port=PORT, analyse=_lines))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{PORT}"
    try:
        with httpx.Client(base_url=base, timeout=10.0) as client:
            yield base, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- the Host check: what defeats DNS rebinding --------------------------------


def test_a_host_header_naming_another_domain_is_refused() -> None:
    """The rebinding case. The attacker's domain resolves to 127.0.0.1 after the
    page loads, so the browser sends ITS name in Host — which cannot be this one."""
    assert host_allowed("evil.example:8791", port=PORT, allowed=frozenset({"127.0.0.1"})) is False


def test_the_loopback_names_a_browser_actually_sends_are_allowed() -> None:
    allowed = frozenset({"127.0.0.1", "localhost", "[::1]"})
    for name in ("127.0.0.1", "localhost", "[::1]"):
        assert host_allowed(f"{name}:{PORT}", port=PORT, allowed=allowed) is True


def test_a_missing_host_is_refused_rather_than_waved_through() -> None:
    """HTTP/1.1 requires it. The only clients that omit it are not browsers."""
    assert host_allowed(None, port=PORT, allowed=frozenset({"127.0.0.1"})) is False
    assert host_allowed("", port=PORT, allowed=frozenset({"127.0.0.1"})) is False


def test_the_right_host_on_the_wrong_port_is_refused() -> None:
    # Another loopback service on the same machine is not this one.
    assert host_allowed("127.0.0.1:9999", port=PORT, allowed=frozenset({"127.0.0.1"})) is False
    assert host_allowed("127.0.0.1", port=PORT, allowed=frozenset({"127.0.0.1"})) is False


def test_an_unparseable_port_is_refused_rather_than_raising() -> None:
    assert host_allowed("127.0.0.1:eighty", port=PORT, allowed=frozenset({"127.0.0.1"})) is False


def test_a_bare_ipv6_literal_is_not_mistaken_for_a_host_and_port() -> None:
    """Splitting on the last colon turns `[::1]` into host `[:` and port `1]`."""
    assert host_allowed("[::1]", port=PORT, allowed=frozenset({"[::1]"})) is False
    assert host_allowed(f"[::1]:{PORT}", port=PORT, allowed=frozenset({"[::1]"})) is True


# --- the Origin check: what defeats the plain cross-origin POST ----------------


def test_a_foreign_origin_is_refused() -> None:
    assert (
        origin_allowed("http://evil.example", port=PORT, allowed=frozenset({"127.0.0.1"})) is False
    )
    assert (
        origin_allowed(f"http://evil.example:{PORT}", port=PORT, allowed=frozenset({"127.0.0.1"}))
        is False
    )


def test_the_servers_own_origin_is_allowed() -> None:
    assert (
        origin_allowed(f"http://127.0.0.1:{PORT}", port=PORT, allowed=frozenset({"127.0.0.1"}))
        is True
    )


def test_an_absent_origin_is_allowed_because_the_app_itself_sends_none() -> None:
    """Same-origin GETs and non-browser clients send no Origin. The Host check is
    what covers that case."""
    assert origin_allowed(None, port=PORT, allowed=frozenset({"127.0.0.1"})) is True


def test_a_null_origin_is_refused() -> None:
    """Sandboxed iframes and file:// pages send `null`, and neither is this app."""
    assert origin_allowed("null", port=PORT, allowed=frozenset({"127.0.0.1"})) is False


def test_an_https_origin_on_the_same_name_is_still_a_different_origin() -> None:
    assert (
        origin_allowed(f"https://127.0.0.1:{PORT}", port=PORT, allowed=frozenset({"127.0.0.1"}))
        is False
    )


# --- end to end, over a real socket --------------------------------------------


def test_the_app_and_the_endpoint_share_one_origin(served: tuple[str, httpx.Client]) -> None:
    """Which is what makes the Origin check strict rather than advisory: with a
    separate API port, cross-origin would be the normal case."""
    _base, client = served
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.css").status_code == 200
    assert client.post("/analyse", json={"ticker": "AAPL"}).status_code == 200


def test_a_cross_origin_post_is_refused_before_anything_runs(
    served: tuple[str, httpx.Client],
) -> None:
    _base, client = served
    response = client.post(
        "/analyse", json={"ticker": "AAPL"}, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["refused"] == "cross_origin"


def test_a_rebound_host_is_refused(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    response = client.post("/analyse", json={"ticker": "AAPL"}, headers={"Host": "evil.example"})
    assert response.status_code == 421
    assert response.json()["refused"] == "host_not_loopback"


def test_the_stream_is_newline_delimited_json(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    body = client.post("/analyse", json={"ticker": "AAPL", "horizon_days": 10}).text
    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert events[0]["stage"] == "filing"
    assert events[-1] == {"event": "result", "horizon_days": 10, "marking": "settled"}


def test_a_failing_analysis_ends_the_stream_with_a_reason(tmp_path: Path) -> None:
    """The response is already open with a 200 by the time a run can fail, so the
    failure cannot become a status code. It becomes a final line."""

    def broken(_ticker: str, _horizon: int) -> Iterator[dict[str, object]]:
        yield {"event": "progress", "stage": "filing"}
        raise RuntimeError("the model went away")

    server = build(Config(root=tmp_path, port=PORT + 1, analyse=broken))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{PORT + 1}", timeout=10.0) as client:
            body = client.post("/analyse", json={"ticker": "AAPL"}).text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    last = json.loads(body.splitlines()[-1])
    assert last["event"] == "failed"
    assert "the model went away" in last["why"]


# --- what else the endpoint refuses --------------------------------------------


@pytest.mark.parametrize(
    "payload,kind",
    [
        ({"ticker": "../../etc/passwd"}, "bad_ticker"),
        ({"ticker": "TOOLONGTICKER"}, "bad_ticker"),
        ({"ticker": ""}, "bad_ticker"),
        ({"ticker": "AAPL", "horizon_days": 3}, "bad_horizon"),
        ({"ticker": "AAPL", "horizon_days": 250}, "bad_horizon"),
        ({}, "unreadable_request"),
    ],
)
def test_a_request_the_server_will_not_act_on_is_named(
    served: tuple[str, httpx.Client], payload: dict[str, object], kind: str
) -> None:
    _base, client = served
    response = client.post("/analyse", json=payload)
    assert response.status_code == 400
    assert response.json()["refused"] == kind


def test_the_three_offered_horizons_are_accepted(served: tuple[str, httpx.Client]) -> None:
    """Ten and twenty-one are uncalibrated, not forbidden — they are marked, which
    is a different thing from being refused."""
    _base, client = served
    for horizon in (5, 10, 21):
        assert (
            client.post("/analyse", json={"ticker": "AAPL", "horizon_days": horizon}).status_code
            == 200
        )


def test_an_oversized_body_is_refused_before_it_is_parsed(
    served: tuple[str, httpx.Client],
) -> None:
    _base, client = served
    response = client.post(
        "/analyse", content=b"x" * 9000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_another_path_is_not_an_endpoint(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    assert client.post("/anything", json={"ticker": "AAPL"}).status_code == 404


def test_a_traversal_out_of_the_app_directory_is_refused(
    served: tuple[str, httpx.Client], tmp_path: Path
) -> None:
    """Compared on resolved paths rather than by looking for `..` in the request:
    the encodings of that are endless and the comparison holds whatever was sent.

    Sent over a RAW SOCKET. An HTTP client normalises `..` out of the path before
    it goes on the wire, so a client-based test here would be testing the client:
    the server would receive `/outside.txt`, refuse it for not existing, and the
    test would pass whether or not the guard were there at all."""
    _base, _client = served
    (tmp_path.parent / "outside.txt").write_text("LEAKED", encoding="utf-8")

    for path in ("/../outside.txt", "/assets/../../outside.txt", "/%2e%2e/outside.txt"):
        response = _raw(f"GET {path} HTTP/1.1")
        assert "404" in response.split("\r\n")[0], path
        assert "LEAKED" not in response, path

    # The file that IS inside is still served, so this is not refusing everything.
    assert "200" in _raw("GET /assets/app.css HTTP/1.1").split("\r\n")[0]


def test_the_responses_say_not_to_embed_or_sniff_them(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_health_answers_without_starting_anything(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    assert client.get("/health").json() == {"ok": True}


def test_an_unreadable_content_length_is_refused(served: tuple[str, httpx.Client]) -> None:
    """Sent raw, because a client computes this header itself and would never send
    a bad one — so a client-based test could not reach this branch at all."""
    _base, _client = served
    request = (
        "POST /analyse HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{PORT}\r\n"
        "Content-Length: twelve\r\n"
        "Connection: close\r\n\r\n"
    )
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    sock.sendall(request.encode())
    chunks: list[bytes] = []
    while chunk := sock.recv(4096):
        chunks.append(chunk)
    sock.close()
    assert "bad_length" in b"".join(chunks).decode(errors="replace")


def test_a_get_with_a_rebound_host_never_reaches_the_files(
    served: tuple[str, httpx.Client],
) -> None:
    """The Host check guards static requests too, not only the endpoint: rebinding
    is what lets an attacker's page read this app's markup."""
    _base, client = served
    response = client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 421
    assert "<title>app</title>" not in response.text


# --- the two reads a company page makes ----------------------------------------


READ_PORT = 8792


def _prices(ticker: str) -> dict[str, object]:
    if ticker == "GONE":
        from mapf.serve.server import ReadRefusedError

        raise ReadRefusedError("no price history for GONE: delisted")
    return {"ticker": ticker, "fetched_on": "2026-09-30", "bars": [["2026-09-29", 10.5]]}


def _live_runs(ticker: str) -> list[dict[str, object]]:
    return [{"run_id": "r-1", "ticker": ticker, "anchor_date": "2026-09-29"}]


@pytest.fixture
def reads(tmp_path: Path) -> Iterator[httpx.Client]:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    server = build(
        Config(root=tmp_path, port=READ_PORT, analyse=_lines, prices=_prices, live_runs=_live_runs)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{READ_PORT}", timeout=10.0) as client:
            yield client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_company_page_can_read_a_price_window(reads: httpx.Client) -> None:
    response = reads.get("/prices", params={"ticker": "ko"})
    assert response.status_code == 200
    assert response.json()["ticker"] == "KO", "upper-cased before it reaches the reader"
    assert response.json()["fetched_on"] == "2026-09-30"


def test_a_company_page_can_read_its_live_runs(reads: httpx.Client) -> None:
    response = reads.get("/runs", params={"ticker": "KO"})
    assert response.status_code == 200
    assert response.json()[0]["run_id"] == "r-1"


def test_a_read_refuses_a_string_that_is_not_a_ticker(reads: httpx.Client) -> None:
    """The same pattern `POST /analyse` uses, because the string reaches a cache
    path and a provider query just as that one does."""
    for bad in ("../etc", "", "TOOLONGX", "A B"):
        response = reads.get("/prices", params={"ticker": bad})
        assert response.status_code == 400, bad
        assert response.json()["refused"] == "bad_ticker"


def test_a_read_that_cannot_answer_says_why(reads: httpx.Client) -> None:
    response = reads.get("/prices", params={"ticker": "GONE"})
    assert response.status_code == 502
    assert response.json()["why"] == "no price history for GONE: delisted"


def test_a_read_is_checked_at_the_boundary_like_everything_else(reads: httpx.Client) -> None:
    rebound = {"Host": f"evil.example:{READ_PORT}"}
    response = reads.get("/runs", params={"ticker": "KO"}, headers=rebound)
    assert response.status_code == 421


def test_a_server_started_without_a_reader_says_so(served: tuple[str, httpx.Client]) -> None:
    _base, client = served
    for path in ("/prices", "/runs"):
        response = client.get(path, params={"ticker": "KO"})
        assert response.status_code == 404
        assert response.json()["refused"] == "no_such_endpoint"


def test_no_read_can_start_a_run(reads: httpx.Client) -> None:
    """Reads are GETs and the only route that makes anything exist is the POST.
    A GET to the analysis path is static-file handling, and there is no file."""
    assert reads.get("/analyse", params={"ticker": "KO"}).status_code == 404
