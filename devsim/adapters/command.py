from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class CommandAdapter:
    name = "command"

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise AdapterError("command.run requires with.command")
        timeout = float(payload.get("timeout", 120))
        configured_env = payload.get("env") or {}
        if not isinstance(configured_env, dict):
            raise AdapterError("command.run with.env must be a mapping")
        environment = os.environ.copy()
        environment.update({str(k): str(v) for k, v in configured_env.items()})
        python_bin = str(Path(sys.executable).parent)
        environment["PATH"] = python_bin + os.pathsep + environment.get("PATH", "")
        environment.update(
            {
                "DEVSIM_SEED": str(context.seed),
                "DEVSIM_RUN_ID": context.run_id,
                "DEVSIM_PROJECT": context.project_dir,
                "DEVSIM_SCENARIO": context.scenario_name,
                "DEVSIM_VIRTUAL_TIME_MS": str(context.virtual_ms),
            }
        )
        cwd = Path(str(payload.get("cwd", self.project_dir)))
        if not cwd.is_absolute():
            cwd = self.project_dir / cwd
        if not cwd.is_dir():
            raise AdapterError(f"command working directory does not exist: {cwd}")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"command timed out after {timeout:g}s: {command}") from exc
        except OSError as exc:
            raise AdapterError(f"could not execute command {command!r}: {exc}") from exc
        result = ActionResult(
            ok=completed.returncode == 0,
            data={
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
        if not result.ok:
            raise AdapterError(
                f"command exited with code {completed.returncode}: {command}\n{completed.stderr.strip()}".strip()
            )
        return result
