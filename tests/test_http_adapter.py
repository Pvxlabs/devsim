from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from devsim.adapters.http import HTTPAdapter
from devsim.errors import AdapterError
from devsim.models import ActionContext
from devsim.rng import DeterministicRNG


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": body}).encode())

    def log_message(self, *_args: object) -> None:
        return


def context(tmp_path: Path) -> ActionContext:
    return ActionContext(str(tmp_path), "run", "sample", 42, 0, 1, DeterministicRNG(42))


def test_http_adapter_sends_json_and_validates_status(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(
            HTTPAdapter(f"http://127.0.0.1:{server.server_port}").execute(
                context(tmp_path),
                {"method": "POST", "path": "/events", "json": {"type": "started"}, "expected_status": 201},
            )
        )
        assert result.data["status"] == 201
        assert result.data["body"] == {"received": {"type": "started"}}
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_adapter_reports_status_mismatch(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(AdapterError, match=r"expected \[200\]"):
            asyncio.run(
                HTTPAdapter(f"http://127.0.0.1:{server.server_port}").execute(
                    context(tmp_path),
                    {"method": "POST", "path": "/events", "json": {}, "expected_status": 200},
                )
            )
    finally:
        server.shutdown()
        thread.join(timeout=2)
