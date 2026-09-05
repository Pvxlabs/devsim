# WebSocket Adapter

`websocket.expect` is a bounded observation adapter. It connects, receives one
message, parses JSON, applies the shared partial JSON expectation engine, and
closes the connection.

```yaml
- at: 0s
  action: websocket.expect
  with:
    url: ws://127.0.0.1:8000/ws/events
    timeout: 5
  expect:
    json:
      type: event.completed
```

This adapter does not provide subscriptions, multiplexing, binary protocols,
or reconnect orchestration.

