"""HTTP HEAD method tests for backend/server.py."""

from __future__ import annotations

import http.client
import threading
from http.server import HTTPServer

import pytest

import backend.server as server_module


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>Futarchy</title></head><body>ok</body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")
    monkeypatch.setattr(server_module, "FRONTEND_DIST", dist)

    httpd = HTTPServer(("127.0.0.1", 0), server_module.BayesHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def _request(port: int, method: str, path: str, headers: dict[str, str] | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body
    finally:
        conn.close()


@pytest.mark.parametrize("path", ["/", "/markets", "/assets/app.js", "/health", "/v1/health"])
def test_head_returns_200_headers_without_body(live_server, path):
    get_status, get_headers, get_body = _request(live_server, "GET", path)
    head_status, head_headers, head_body = _request(live_server, "HEAD", path)

    assert get_status == 200
    assert head_status == 200
    assert head_body == b""
    assert head_headers["content-type"] == get_headers["content-type"]
    assert int(head_headers["content-length"]) == len(get_body)
    assert int(head_headers["content-length"]) > 0


def test_head_root_json_accept_returns_200_json_headers_without_body(live_server):
    headers = {"Accept": "application/json"}
    get_status, get_headers, get_body = _request(live_server, "GET", "/", headers=headers)
    head_status, head_headers, head_body = _request(live_server, "HEAD", "/", headers=headers)

    assert get_status == 200
    assert head_status == 200
    assert head_body == b""
    assert head_headers["content-type"] == "application/json"
    assert int(head_headers["content-length"]) == len(get_body)


def test_head_unknown_api_route_returns_404_without_body(live_server):
    head_status, head_headers, head_body = _request(live_server, "HEAD", "/v1/does-not-exist")
    assert head_status == 404
    assert head_body == b""
    assert head_headers["content-type"] == "application/json"
