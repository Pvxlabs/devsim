from __future__ import annotations

import asyncio
import json
from typing import Any

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class WebSocketAdapter:
    name = "websocket.expect"

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        url = payload.get("url")
        if not isinstance(url, str) or not url.startswith(("ws://", "wss://")):
            raise AdapterError("websocket.expect requires a ws:// or wss:// url")
        timeout = float(payload.get("timeout", 30))
        headers = payload.get("headers") or None
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise AdapterError("websocket.expect requires the 'websockets' package") from exc
        try:
            async with connect(url, additional_headers=headers, open_timeout=timeout) as socket:
                message = await asyncio.wait_for(socket.recv(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise AdapterError(f"WebSocket receive timed out after {timeout:g}s: {url}") from exc
        except Exception as exc:
            raise AdapterError(f"WebSocket connection failed for {url}: {exc}") from exc
        try:
            actual = json.loads(message) if isinstance(message, str) else message
        except (TypeError, json.JSONDecodeError) as exc:
            raise AdapterError("websocket.expect received invalid JSON") from exc
        return ActionResult(True, {"url": url, "json": actual, "message": message})
