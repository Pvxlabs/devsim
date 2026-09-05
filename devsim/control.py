"""Local-only preview control plane and minimal observation UI."""

from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .cli import _start_managed_scenario, inspect_run, status_result
from .config import discover_scenarios
from .errors import DevSimError, ScenarioError
from .lifecycle import Lifecycle
from .runtime import RuntimeOwnership
from .state import StateStore


UI_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>DevSim Control</title>
<style>
body{font:14px system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#17202a;background:#f6f8fa}
header{display:flex;justify-content:space-between;align-items:center;gap:16px} h1{font-size:22px;margin:0}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:18px}
section{background:white;border:1px solid #d8dee4;border-radius:6px;padding:14px} h2{font-size:15px;margin:0 0 10px}
dl{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:0} dt{color:#57606a} dd{margin:0;font-family:ui-monospace,monospace;overflow-wrap:anywhere}
button,select,input{font:inherit;padding:6px 8px;border:1px solid #afb8c1;border-radius:5px;background:#fff} button{cursor:pointer}
.controls{display:flex;flex-wrap:wrap;gap:7px}.timeline{width:100%;border-collapse:collapse}.timeline th,.timeline td{padding:6px;border-bottom:1px solid #d8dee4;text-align:left;font-size:12px}
#message{color:#57606a;min-height:20px}
</style></head><body><header><h1>DevSim Control</h1><span id="message"></span></header>
<main><section><h2>Runtime</h2><dl id="status"></dl></section>
<section><h2>Controls</h2><div class="controls"><button onclick="post('/reset')">Reset</button><button onclick="post('/runtime/pause')">Pause</button><button onclick="post('/runtime/resume')">Resume</button><button onclick="post('/runtime/stop')">Stop</button></div><p><label>Scenario <select id="scenario"></select></label></p><p><label>Profile <select id="profile"></select></label> <label>Seed <input id="seed" type="number" value="42"></label></p><div class="controls"><button onclick="start()">Start</button><button onclick="seed()">Seed</button></div></section>
<section style="grid-column:1/-1"><h2>Run timeline</h2><table class="timeline"><thead><tr><th>Sequence</th><th>Virtual time</th><th>Action</th><th>Status</th><th>Duration</th></tr></thead><tbody id="timeline"></tbody></table></section></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function get(path){const r=await fetch(path);const j=await r.json();if(!r.ok)throw Error(j.error?.message||'request failed');return j}
async function post(path,body={}){try{const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw Error(j.error?.message||'request failed');document.querySelector('#message').textContent='OK';await refresh()}catch(e){document.querySelector('#message').textContent=e.message}}
async function start(){await post('/scenarios/'+encodeURIComponent(document.querySelector('#scenario').value)+'/start',{seed:Number(document.querySelector('#seed').value)})}
async function seed(){await post('/seed',{seed:Number(document.querySelector('#seed').value),profile:document.querySelector('#profile').value})}
async function refresh(){try{const [s,sc]=await Promise.all([get('/status'),get('/scenarios')]);const state=s.state;const fields={Project:state.project,Environment:state.environment,Status:state.status,Scenario:state.scenario,Seed:state.seed,'Clock speed':state.clock_speed,'Virtual time':state.virtual_time_ms,'Events executed':state.events_executed,'Events failed':state.events_failed,Heartbeat:state.heartbeat,'Current run ID':state.run_id};document.querySelector('#status').innerHTML=Object.entries(fields).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');const sel=document.querySelector('#scenario');const old=sel.value;sel.innerHTML=sc.scenarios.map(x=>`<option value="${esc(x.name)}">${esc(x.name)}</option>`).join('');if(old)sel.value=old;const profile=document.querySelector('#profile');const oldProfile=profile.value;profile.innerHTML=(sc.profiles||['default']).map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');if(oldProfile)profile.value=oldProfile;const observableStatuses=['running','paused','completed','failed'];if(state.run_id&&observableStatuses.includes(state.status)){const run=await get('/runs/'+encodeURIComponent(state.run_id));document.querySelector('#timeline').innerHTML=run.timeline.map(x=>`<tr><td>${esc(x.sequence)}</td><td>${esc(x.virtual_time_ms)}</td><td>${esc(x.action)}</td><td>${esc(x.status)}</td><td>${esc(x.duration_ms)}</td></tr>`).join('')}}catch(e){document.querySelector('#message').textContent=e.message}}
refresh();setInterval(refresh,1000);
</script></body></html>"""


def serve(project_dir: Path, manifest, *, host: str = "127.0.0.1", port: int = 8001, token: str | None = None) -> dict[str, Any]:
    if not _local_host(host) and not token:
        raise DevSimError("CONTROL_AUTH_REQUIRED: non-local control binding requires --token")
    server = _make_server(project_dir, manifest, host, port, token)
    print(f"DevSim Control UI: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"ok": True, "status": "stopped", "host": host, "port": server.server_port}


def _make_server(project_dir: Path, manifest, host: str, port: int, token: str | None):
    store = StateStore(project_dir)
    ownership = RuntimeOwnership(project_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path).path
            try:
                if path in {"/", "/index.html"}:
                    return self._send(200, UI_HTML, "text/html; charset=utf-8")
                if path == "/health":
                    return self._send_json(200, {"ok": True, "status": "healthy", "project": manifest.project_name})
                if path == "/status":
                    return self._send_json(200, status_result(project_dir, manifest, store, ownership))
                if path == "/scenarios":
                    profiles = sorted((manifest.seed_config.get("profiles") or {}).keys()) if manifest.seed_config else []
                    profiles = sorted({"default", *profiles})
                    return self._send_json(200, {"ok": True, "scenarios": [{"name": item.name, "description": item.description, "version": item.version} for item in discover_scenarios(project_dir, manifest)], "profiles": profiles})
                if path == "/runs":
                    return self._send_json(200, {"ok": True, "runs": _runs(store)})
                if path.startswith("/runs/"):
                    run_id = path.rsplit("/", 1)[1]
                    return self._send_json(200, _run_detail(store, run_id))
                return self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "route not found"}})
            except Exception as exc:
                self._error(exc)

        def do_POST(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path.startswith("/scenarios/") and path.endswith("/start"):
                    name = path[len("/scenarios/"):-len("/start")].strip("/")
                    scenario = next((item for item in discover_scenarios(project_dir, manifest) if item.name == name), None)
                    if scenario is None:
                        raise ScenarioError(f"scenario {name!r} was not found")
                    started = _start_managed_scenario(project_dir, manifest, store, ownership, scenario, int(body.get("seed", 0)), max_events=body.get("max_events"), max_duration=body.get("max_duration"))
                    return self._send_json(200, {"ok": True, "operation": "scenario.start", **started})
                if path == "/runtime/pause":
                    return self._send_json(200, _runtime_command("pause"))
                if path == "/runtime/resume":
                    return self._send_json(200, _runtime_command("run"))
                if path == "/runtime/stop":
                    return self._send_json(200, _runtime_stop())
                if path == "/reset":
                    state = Lifecycle(project_dir, manifest, store).run("reset", seed=int(body.get("seed", 0)), profile=str(body.get("profile", "default")))
                    ownership.clear()
                    return self._send_json(200, {"ok": True, "operation": "reset", "state": state.to_dict()})
                if path == "/seed":
                    state = Lifecycle(project_dir, manifest, store).run("seed", seed=int(body.get("seed", 0)), profile=str(body.get("profile", "default")))
                    return self._send_json(200, {"ok": True, "operation": "seed", "state": state.to_dict()})
                return self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "route not found"}})
            except Exception as exc:
                self._error(exc)

        def _runtime_command(self, command: str) -> dict[str, Any]:
            state = store.load(manifest.project_name)
            if not ownership.status() or not ownership.status().get("process_alive"):
                raise ScenarioError("no managed runtime is running")
            ownership.request(command)
            state.status = "paused" if command == "pause" else "running"
            state.last_operation = "scenario.pause" if command == "pause" else "scenario.resume"
            store.save(state)
            return {"ok": True, "operation": state.last_operation, "state": state.to_dict()}

        def _runtime_stop(self) -> dict[str, Any]:
            state = store.load(manifest.project_name)
            state.stop_requested = True
            state.last_operation = "scenario.stop"
            store.save(state)
            if ownership.status() and ownership.status().get("process_alive"):
                ownership.request("stop")
            return {"ok": True, "operation": "scenario.stop", "state": state.to_dict()}

        def _authorized(self) -> bool:
            if _local_host(host) and not token:
                return True
            provided = self.headers.get("Authorization", "").removeprefix("Bearer ") or self.headers.get("X-DevSim-Token", "")
            if secrets.compare_digest(provided, token or ""):
                return True
            self._send_json(401, {"ok": False, "error": {"code": "control_unauthorized", "message": "bearer token required"}})
            return False

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1024 * 1024:
                raise DevSimError("control request body is too large")
            if not length:
                return {}
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise DevSimError("control request body must be an object")
            return value

        def _send_json(self, status: int, value: dict[str, Any]) -> None:
            self._send(status, json.dumps(value, sort_keys=True, ensure_ascii=True), "application/json; charset=utf-8")

        def _send(self, status: int, content: str, content_type: str) -> None:
            raw = content.encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def _error(self, exc: Exception) -> None:
            self._send_json(400, {"ok": False, "error": {"code": getattr(exc, "code", "control_error"), "message": str(exc)}})

    return ThreadingHTTPServer((host, port), Handler)


def _run_detail(store: StateStore, run_id: str) -> dict[str, Any]:
    events = store.read_run_events(run_id)
    detail = inspect_run(store, run_id)
    detail["timeline"] = [
        {key: event.get(key) for key in ("sequence", "virtual_time_ms", "action", "status", "duration_ms")}
        for event in events if event.get("status") in {"completed", "failed"}
    ]
    detail["artifacts"] = [
        event["result"]["path"]
        for event in events
        if event.get("status") == "completed"
        and isinstance(event.get("result"), dict)
        and isinstance(event["result"].get("path"), str)
    ]
    return detail


def _runs(store: StateStore) -> list[dict[str, Any]]:
    if not store.runs_dir.exists():
        return []
    result = []
    for path in sorted(store.runs_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            result.append(inspect_run(store, path.stem))
        except Exception:
            continue
    return result


def _local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}
