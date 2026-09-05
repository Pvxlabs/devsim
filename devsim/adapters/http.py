from __future__ import annotations

import asyncio
import json
from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class HTTPAdapter:
    name = "http"
    methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        method = str(payload.get("method", "GET")).upper()
        if method not in self.methods:
            raise AdapterError(f"unsupported HTTP method {method!r}")
        path = payload.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise AdapterError("api.request requires a path starting with '/'")
        url = f"{self.base_url}{path}"
        headers = {str(k): str(v) for k, v in (payload.get("headers") or {}).items()}
        body = payload.get("json")
        data = None
        if body is not None:
            data = json.dumps(body, sort_keys=True).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        expected = payload.get("expected_status", payload.get("status"))
        if isinstance(expected, int) and not isinstance(expected, bool):
            expected_statuses = {expected}
        elif isinstance(expected, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in expected):
            expected_statuses = set(expected)
        elif expected is None:
            expected_statuses = set()
        else:
            raise AdapterError("api.request expected_status must be an integer or list of integers")
        try:
            response = await asyncio.to_thread(self._request, method, url, headers, data, float(payload.get("timeout", 30)))
        except URLError as exc:
            raise AdapterError(f"HTTP request failed for {url}: {exc.reason}") from exc
        actual_status, response_headers, response_body = response
        if expected_statuses and actual_status not in expected_statuses:
            raise AdapterError(f"HTTP {method} {url} returned {actual_status}, expected {sorted(expected_statuses)}")
        return ActionResult(
            ok=200 <= actual_status < 400,
            data={
                "method": method,
                "url": url,
                "status": actual_status,
                "headers": response_headers,
                "body": response_body,
            },
        )

    @staticmethod
    def _request(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float) -> tuple[int, dict[str, str], Any]:
        request = Request(url, data=data, headers=headers, method=method)
        try:
            response: HTTPResponse = urlopen(request, timeout=timeout)
        except HTTPError as response:
            return response.code, dict(response.headers.items()), _decode_body(response)
        return response.status, dict(response.headers.items()), _decode_body(response)


def _decode_body(response: HTTPResponse) -> Any:
    raw = response.read()
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
