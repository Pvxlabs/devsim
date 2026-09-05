# Preview Control API

`devsim serve` starts a small local control plane for the current project. It
binds to `127.0.0.1:8001` by default and has no external service dependency.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness and project name |
| GET | `/status` | Runtime state and ownership |
| GET | `/scenarios` | Available scenarios |
| GET | `/runs` | Recent run summaries |
| GET | `/runs/{id}` | Run timeline and artifact paths |
| POST | `/scenarios/{name}/start` | Start a persistent scenario |
| POST | `/runtime/pause` | Freeze the virtual clock |
| POST | `/runtime/resume` | Resume the virtual clock |
| POST | `/runtime/stop` | Request a graceful stop |
| POST | `/reset` | Run the canonical reset operation |
| POST | `/seed` | Run seed with a profile and seed |

POST requests use JSON, for example `{"seed": 42, "profile": "normal"}`.

Localhost requests do not need a token. If the server is explicitly bound to a
non-local address, `--token` is required and clients must send `Authorization:
Bearer <token>` or `X-DevSim-Token`.
