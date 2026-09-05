from __future__ import annotations

import uuid
from pathlib import Path

from .adapters.command import CommandAdapter
from .errors import LifecycleError
from .models import CommandSpec, Manifest, RuntimeState
from .safety import assert_safe
from .state import StateStore


class Lifecycle:
    def __init__(self, project_dir: Path, manifest: Manifest, state_store: StateStore):
        self.project_dir = project_dir
        self.manifest = manifest
        self.state_store = state_store
        self.command_adapter = CommandAdapter(project_dir)

    def run(self, operation: str, *, seed: int = 0) -> RuntimeState:
        assert_safe(self.manifest, operation)
        if operation == "reset":
            for step in ("reset", "migrate"):
                self._run_step(step, seed)
            self._run_seed(seed)
            state = self.state_store.reset_runtime(self.manifest.project_name)
            state.last_operation = "reset"
            self.state_store.save(state)
            return state
        if operation == "seed":
            self._run_seed(seed)
            state = self.state_store.load(self.manifest.project_name)
            state.status = "seeded"
            state.seed = seed
            state.last_operation = "seed"
            state.error = None
            self.state_store.save(state)
            return state
        self._run_step(operation, seed)
        state = self.state_store.load(self.manifest.project_name)
        state.status = "up" if operation == "up" else "down"
        state.last_operation = operation
        state.error = None
        self.state_store.save(state)
        return state

    def _run_seed(self, seed: int) -> None:
        if self.manifest.seed_command is None:
            return
        run_id = str(uuid.uuid4())
        spec = self.manifest.seed_command
        self._run_command(spec, seed, run_id, "seed")

    def _run_step(self, operation: str, seed: int) -> None:
        if operation not in self.manifest.lifecycle:
            raise LifecycleError(f"no lifecycle command configured for {operation}")
        self._run_command(self.manifest.lifecycle[operation], seed, str(uuid.uuid4()), operation)

    def _run_command(self, spec: CommandSpec, seed: int, run_id: str, operation: str) -> None:
        import asyncio

        try:
            asyncio.run(
                self.command_adapter.execute(
                    _context(self.project_dir, run_id, self.manifest.project_name, seed),
                    {"command": spec.command, "timeout": spec.timeout, "env": spec.env, "cwd": spec.cwd or str(self.project_dir)},
                )
            )
        except Exception as exc:
            state = self.state_store.load(self.manifest.project_name)
            state.status = "failed"
            state.last_operation = operation
            state.error = {"code": getattr(exc, "code", "lifecycle_error"), "message": str(exc)}
            self.state_store.save(state)
            raise


def _context(project_dir: Path, run_id: str, project: str, seed: int):
    from .models import ActionContext
    from .rng import DeterministicRNG

    return ActionContext(str(project_dir), run_id, project, seed, 0, 0, DeterministicRNG(seed))
