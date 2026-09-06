"""Read-only productization helpers for project discovery and validation."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .config import discover_scenarios, load_manifest
from . import __version__
from .models import Manifest
from .safety import assert_observation_url_safe


CAPABILITIES: dict[str, Any] = {
    "version": __version__,
    "manifest_versions": [1],
    "scenario_versions": [1],
    "adapters": ["http", "command", "websocket", "browser"],
    "seed": ["custom", "postgres-schema-aware"],
    "runtime": ["finite", "persistent", "pause", "resume", "replay"],
    "observation": ["http", "websocket", "browser", "screenshot"],
    "control": ["cli", "api", "ui"],
}


def capabilities() -> dict[str, Any]:
    return {"ok": True, "data": json.loads(json.dumps(CAPABILITIES))}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


_DISCOVERY_PRUNE_DIRS = {
    ".devsim",
    ".git",
    ".next",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def _compose_files(project_dir: Path, *, max_depth: int = 5) -> list[Path]:
    """Find compose manifests without walking dependency/build trees."""
    found: list[Path] = []
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)
        relative_parts = root_path.relative_to(project_dir).parts
        if len(relative_parts) >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [item for item in dirs if item not in _DISCOVERY_PRUNE_DIRS]
        for filename in files:
            lowered = filename.lower()
            if (lowered.startswith("compose") or lowered.startswith("docker-compose")) and lowered.endswith((".yml", ".yaml")):
                found.append(root_path / filename)
    return sorted(found)


def _database_detection(project_dir: Path, manifest: Manifest | None, manifest_error: Exception | None) -> dict[str, Any]:
    if manifest is not None:
        return {"engine": manifest.database_engine, "confidence": "high", "source": "devsim.yaml"}
    root_files = [project_dir / name for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "package.json", "Dockerfile")]
    haystack = "\n".join(_read_text(path).lower() for path in [*root_files, *_compose_files(project_dir)])
    if any(marker in haystack for marker in ("postgres", "postgresql", "psycopg", "asyncpg", "pg_")):
        confidence = "high" if "postgres" in haystack or "postgresql" in haystack else "medium"
        return {"engine": "postgres", "confidence": confidence, "source": "project files"}
    if manifest_error and "postgres" in str(manifest_error).lower():
        return {"engine": "postgres", "confidence": "medium", "source": "manifest"}
    return {"engine": None, "confidence": "unknown", "source": None}


def _migration_detection(project_dir: Path) -> dict[str, Any]:
    candidates = [path for path in (project_dir / "migrations", project_dir / "alembic", project_dir / "prisma" / "migrations", project_dir / "db" / "migrations") if path.is_dir()]
    files = [name for name in ("alembic.ini", "manage.py") if (project_dir / name).exists()]
    if candidates or files:
        return {"detected": True, "paths": [str(path.relative_to(project_dir)) for path in candidates] + files, "confidence": "high"}
    return {"detected": False, "paths": [], "confidence": "unknown"}


def _infer_application_urls(project_dir: Path, manifest: Manifest | None) -> list[str]:
    if manifest is not None:
        return [manifest.base_url]
    urls: set[str] = set()
    for compose_path in _compose_files(project_dir):
        text = _read_text(compose_path)
        for port in re.findall(r"(?:^|[-\s])([0-9]{2,5}):[0-9]{2,5}", text):
            if port not in {"5432", "8001"}:
                urls.add(f"http://127.0.0.1:{port}")
    package = _read_text(project_dir / "package.json")
    if package and re.search(r"\b(next|vite|nuxt|react|svelte|vue)\b", package, re.I):
        urls.add("http://127.0.0.1:3000")
    return sorted(urls)


def detect_project(project_dir: Path) -> dict[str, Any]:
    """Inspect a repository without creating files, processes, or database state."""
    project_dir = project_dir.resolve()
    manifest_path = project_dir / "devsim.yaml"
    manifest: Manifest | None = None
    manifest_error: Exception | None = None
    if manifest_path.exists():
        try:
            manifest = load_manifest(project_dir)
        except Exception as exc:
            manifest_error = exc

    scenarios_path = manifest.scenarios_path if manifest else "devsim/scenarios"
    scenario_dir = project_dir / scenarios_path
    seed_configured = bool(manifest and (manifest.seed_command or manifest.seed_config))
    browser_configured = bool(manifest and ("browser" in manifest.adapter_types or manifest.observation.get("browser")))
    preset_names = sorted(manifest.presets) if manifest else []
    scenario_files = sorted(str(path.relative_to(project_dir)) for path in scenario_dir.glob("*.y*ml")) if scenario_dir.is_dir() else []
    existing_devsim = {
        "directory": (project_dir / "devsim").is_dir(),
        "scenarios": scenario_files,
        "seed": (project_dir / "devsim" / "seed.yaml").exists(),
    }
    compose_files = _compose_files(project_dir)
    project_detected = project_dir.is_dir() and (any((project_dir / marker).exists() for marker in ("devsim.yaml", "pyproject.toml", "package.json", "Dockerfile", "AGENTS.md", "devsim")) or bool(compose_files))
    if manifest_error:
        integration = "partial"
    elif manifest is None:
        integration = "partial" if existing_devsim["directory"] or scenario_files else "no"
    elif seed_configured and scenario_files and preset_names and set(manifest.lifecycle) >= {"up", "migrate", "reset", "down"}:
        integration = "yes"
    else:
        integration = "partial"

    return {
        "ok": True,
        "project_detected": project_detected,
        "integration": integration,
        "manifest": str(manifest_path) if manifest_path.exists() else None,
        "manifest_status": "valid" if manifest else "invalid" if manifest_error else "missing",
        "manifest_error": str(manifest_error) if manifest_error else None,
        "database": _database_detection(project_dir, manifest, manifest_error),
        "migrations": _migration_detection(project_dir),
        "application_urls": _infer_application_urls(project_dir, manifest),
        "compose": {"detected": bool(compose_files), "paths": [str(path.relative_to(project_dir)) for path in compose_files]},
        "existing_devsim": existing_devsim,
        "agents": {"present": (project_dir / "AGENTS.md").exists()},
        "capabilities": {"seed": seed_configured, "scenario": bool(scenario_files), "browser": browser_configured},
        "seed": {"configured": seed_configured, "mode": "schema" if manifest and manifest.seed_config else "custom" if manifest and manifest.seed_command else None},
        "scenarios": {"path": scenarios_path if scenario_dir.exists() else None, "count": len(scenario_files), "files": scenario_files},
        "browser": {"configured": browser_configured, "pages": sorted((manifest.observation.get("browser", {}).get("pages") or {}).keys()) if manifest and isinstance(manifest.observation.get("browser"), dict) else []},
        "presets": {"configured": bool(preset_names), "names": preset_names},
    }


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **extra}


def validate_project(project_dir: Path) -> dict[str, Any]:
    """Validate integration files and references without running project code."""
    project_dir = project_dir.resolve()
    try:
        manifest = load_manifest(project_dir)
        checks: list[dict[str, Any]] = [_check("manifest", "PASS", "devsim.yaml is valid")]
    except Exception as exc:
        error = _check("manifest", "FAIL", str(exc), code="INVALID_MANIFEST")
        return {"ok": False, "status": "INVALID", "checks": [error], "errors": [error]}

    mode_ok = manifest.environment_mode.lower() in {"development", "dev", "test", "preview"}
    checks.append(_check("environment", "PASS" if mode_ok else "FAIL", f"environment.mode={manifest.environment_mode}"))
    checks.append(_check("database", "PASS" if manifest.database_engine == "postgres" else "FAIL", f"engine={manifest.database_engine}"))
    required = ("up", "migrate", "reset", "down")
    missing = [name for name in required if name not in manifest.lifecycle]
    checks.append(_check("lifecycle", "PASS" if not missing else "FAIL", "all standard lifecycle commands configured" if not missing else f"missing: {', '.join(missing)}"))
    for name, spec in manifest.lifecycle.items():
        command = spec.command.strip().split()[0] if spec.command.strip() else ""
        available = bool(command) and (shutil.which(command) is not None or command in {"bash", "sh", "python", "python3"} or (project_dir / command).exists())
        if not available:
            checks.append(_check(f"lifecycle.{name}", "WARN", f"executable not found locally: {command}"))

    seed_ok = bool(manifest.seed_command) or (
        bool(manifest.seed_config)
        and manifest.seed_config.get("mode") == "schema"
        and isinstance(manifest.seed_config.get("plan"), dict)
    )
    checks.append(_check("seed", "PASS" if seed_ok else "FAIL", "custom command or schema-aware seed plan configured" if seed_ok else "configure seed.command or seed.mode=schema"))
    try:
        scenarios = discover_scenarios(project_dir, manifest)
        scenario_error = None
    except Exception as exc:
        scenarios, scenario_error = [], str(exc)
    checks.append(_check("scenarios", "PASS" if scenarios and not scenario_error else "FAIL", f"{len(scenarios)} valid scenario(s)" if scenarios and not scenario_error else scenario_error or "no scenario files under configured path"))

    preset_errors: list[str] = []
    scenario_map = {item.name: item for item in scenarios}
    for profile, value in manifest.presets.items():
        if not isinstance(value, dict) or not isinstance(value.get("scenario"), str):
            preset_errors.append(f"{profile}: scenario is required")
        elif value["scenario"] not in scenario_map:
            preset_errors.append(f"{profile}: scenario {value['scenario']!r} was not found")
        elif scenario_map[value["scenario"]].runtime_mode != "persistent":
            preset_errors.append(f"{profile}: scenario must be persistent")
    checks.append(_check("presets", "PASS" if manifest.presets and not preset_errors else "FAIL", f"{len(manifest.presets)} preset(s)" if manifest.presets and not preset_errors else "; ".join(preset_errors) or "no preview presets configured"))

    browser = manifest.observation.get("browser") if isinstance(manifest.observation.get("browser"), dict) else {}
    pages = browser.get("pages") or {}
    browser_configured = "browser" in manifest.adapter_types or bool(browser)
    browser_errors: list[str] = []
    if browser_configured and not isinstance(pages, dict):
        browser_errors.append("observation.browser.pages must be a mapping")
    if isinstance(pages, dict):
        browser_base_url = str(browser.get("base_url") or manifest.base_url)
        try:
            assert_observation_url_safe(browser_base_url)
        except Exception as exc:
            browser_errors.append(str(exc))
        for name, page in pages.items():
            path = page.get("path") if isinstance(page, dict) else page
            if not isinstance(path, str) or not path:
                browser_errors.append(f"{name}: page path is required")
            else:
                try:
                    assert_observation_url_safe(urljoin(browser_base_url.rstrip("/") + "/", path.lstrip("/")))
                except Exception as exc:
                    browser_errors.append(str(exc))
    checks.append(_check("browser", "PASS" if browser_configured and not browser_errors else "WARN" if not browser_configured else "FAIL", "configured" if browser_configured and not browser_errors else "not configured" if not browser_configured else "; ".join(browser_errors)))
    try:
        assert_observation_url_safe(manifest.base_url)
        checks.append(_check("urls", "PASS", manifest.base_url))
    except Exception as exc:
        checks.append(_check("urls", "FAIL", str(exc)))

    failures = [item for item in checks if item["status"] == "FAIL"]
    status = "INVALID" if failures and any(item["name"] in {"manifest", "environment", "database", "urls"} for item in failures) else "PARTIAL" if failures else "READY"
    return {"ok": not failures, "status": status, "checks": checks, "errors": failures}


def project_status(project_dir: Path) -> dict[str, Any]:
    """Report integration completeness; unlike doctor, this performs no setup."""
    detection = detect_project(project_dir)
    if not detection["manifest"]:
        status = "PARTIAL" if detection["integration"] == "partial" else "NOT_CONFIGURED"
        return {
            "ok": True,
            "status": status,
            "ready": False,
            "project": project_dir.name,
            "integration": detection,
            "checks": [],
        }
    validation = validate_project(project_dir)
    return {
        "ok": True,
        "status": validation["status"],
        "ready": validation["status"] == "READY",
        "project": project_dir.name,
        "integration": detection,
        "checks": validation["checks"],
    }


def init_plan(project_dir: Path, *, inspect: bool = False) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    targets = ["devsim.yaml", "devsim/seed.yaml", "devsim/scenarios/", "devsim/scenarios/normal.yaml"]
    existing = [target for target in targets if (project_dir / target.rstrip("/")).exists()]
    actions = [{"action": "KEEP" if target in existing else "CREATE", "path": target} for target in targets]
    return {"project": str(project_dir), "mode": "inspect" if inspect else "standard", "actions": actions}


def inspect_draft(project_dir: Path) -> dict[str, Any]:
    detection = detect_project(project_dir)
    name = project_dir.name or "example-app"
    base_url = (detection.get("application_urls") or ["http://127.0.0.1:8000"])[0]
    draft = (
        "# GENERATED_DRAFT\n"
        "# REVIEW_REQUIRED: heuristic discovery is not canonical project configuration.\n"
        "version: 1\n"
        f"project:\n  name: {name}\n"
        "environment:\n  mode: development\n"
        f"database:\n  engine: {detection['database']['engine'] or 'postgres'}\n  lifecycle: {{}}\n"
        "seed:\n  command: # REVIEW_REQUIRED: provide the project's baseline seed command\n"
        "scenarios:\n  path: devsim/scenarios\n"
        f"runtime:\n  base_url: {base_url}\n  adapters:\n    - type: http\n    - type: command\n"
    )
    return {"ok": True, "status": "GENERATED_DRAFT", "review_required": True, "draft_path": str(project_dir / "devsim.yaml.draft"), "draft": draft, "detection": detection}


def _evidence(path: Path, detail: str, confidence: str = "high") -> dict[str, Any]:
    return {"confidence": confidence, "evidence": [str(path), detail]}


def inspect_project(project_dir: Path) -> dict[str, Any]:
    """Build a bounded, read-only onboarding inspection.

    Inspection reports signals and evidence; it never treats heuristics as
    canonical integration configuration and never executes project commands.
    """
    project_dir = project_dir.resolve()
    detection = detect_project(project_dir)
    package_manager = None
    if (project_dir / "pnpm-lock.yaml").exists():
        package_manager = "pnpm"
    elif (project_dir / "yarn.lock").exists():
        package_manager = "yarn"
    elif (project_dir / "package-lock.json").exists():
        package_manager = "npm"
    elif (project_dir / "uv.lock").exists() or (project_dir / "pyproject.toml").exists():
        package_manager = "uv" if (project_dir / "uv.lock").exists() else "python"

    package_text = _read_text(project_dir / "package.json")
    pyproject_text = _read_text(project_dir / "pyproject.toml")
    compose_files = _compose_files(project_dir)
    compose_present = bool(compose_files)
    framework = None
    for name, marker in (("next", "next"), ("nestjs", "@nestjs/core"), ("react", "react"), ("vite", "vite"), ("fastapi", "fastapi"), ("django", "django")):
        if marker in package_text.lower() or marker in pyproject_text.lower():
            framework = name
            break
    frontend = bool(framework in {"next", "react", "vite"} or (project_dir / "apps" / "web").is_dir() or (project_dir / "frontend").is_dir())
    backend = bool(framework in {"fastapi", "django", "nestjs"} or (project_dir / "src").is_dir() or (project_dir / "app").is_dir())
    auth_indicators = [
        relative for relative in ("auth", "src/auth", "apps/web/src/auth", "middleware.ts", "middleware.js")
        if (project_dir / relative).exists()
    ]
    fixture_paths = [
        str(path.relative_to(project_dir))
        for root in ("fixtures", "test/fixtures", "tests/fixtures", "scripts")
        for path in ([project_dir / root] if (project_dir / root).is_file() else (project_dir / root).glob("*"))
        if path.exists() and ("seed" in path.name.lower() or "fixture" in path.name.lower())
    ]
    startup_candidates = [
        relative for relative in ("scripts/dev-up.sh", "scripts/dev-run", "scripts/local-cluster.sh")
        if (project_dir / relative).exists()
    ] + [str(path.relative_to(project_dir)) for path in compose_files]
    return {
        "ok": True,
        "project": {"name": project_dir.name, "root": str(project_dir)},
        "detected": {
            "runtime": (["node"] if (project_dir / "package.json").exists() else []) + (["python"] if (project_dir / "pyproject.toml").exists() or (project_dir / "requirements.txt").exists() else []),
            "package_manager": package_manager,
            "framework": framework,
            "database": [detection["database"]["engine"]] if detection["database"]["engine"] else [],
            "compose": compose_present,
            "frontend": frontend,
            "backend": backend,
            "authentication": bool(auth_indicators),
        },
        "signals": {
            "database": {**detection["database"], "evidence": [detection["database"].get("source")] if detection["database"].get("source") else []},
            "migrations": detection["migrations"],
            "compose": detection["compose"],
            "startup": {"candidates": startup_candidates, **_evidence(project_dir, "known local lifecycle filenames", "medium")},
            "application_urls": {"values": detection["application_urls"], "confidence": "high" if detection["manifest"] else "medium"},
            "authentication": {"paths": auth_indicators, "confidence": "medium" if auth_indicators else "unknown"},
            "fixtures": {"paths": fixture_paths, "confidence": "medium" if fixture_paths else "unknown"},
            "seed_mechanisms": {"configured": detection["seed"]["configured"], "paths": fixture_paths},
            "browser": detection["browser"],
            "agents": detection["agents"],
        },
        "integration": {"status": detection["integration"], "manifest": detection["manifest"], "existing_devsim": detection["existing_devsim"]},
    }


def onboard_plan(project_dir: Path) -> dict[str, Any]:
    """Return an executable-but-bounded onboarding plan without mutation."""
    project_dir = project_dir.resolve()
    inspection = inspect_project(project_dir)
    detection = detect_project(project_dir)
    actions: list[dict[str, Any]] = []

    def add(capability: str, mode: str, action: str, reason: str | None = None, paths: list[str] | None = None) -> None:
        item: dict[str, Any] = {"capability": capability, "mode": mode, "action": action}
        if reason:
            item["reason"] = reason
        if paths:
            item["paths"] = paths
        actions.append(item)

    if detection["manifest_status"] == "missing":
        add("manifest", "auto", "create devsim.yaml")
    elif detection["manifest_status"] == "invalid":
        add("manifest", "user_required", "repair devsim.yaml", "existing manifest is invalid")
    else:
        add("manifest", "auto", "reuse existing devsim.yaml")
    scaffold_paths: list[str] = []
    if detection["manifest_status"] == "missing":
        scaffold_paths.append("devsim.yaml")
    if not detection["existing_devsim"]["directory"]:
        scaffold_paths.append("devsim/")
    if not detection["seed"]["configured"] and not detection["existing_devsim"]["seed"]:
        scaffold_paths.append("devsim/seed.yaml")
    if detection["scenarios"]["count"] == 0:
        scaffold_paths.extend(["devsim/scenarios/", "devsim/scenarios/normal.yaml"])
    add(
        "scaffold",
        "auto",
        "create missing standard DevSim paths" if scaffold_paths else "reuse existing DevSim integration paths",
        paths=scaffold_paths or None,
    )
    if set(detection["presets"]["names"]) >= {"minimal", "normal", "active"}:
        add("presets", "auto", "reuse existing preview profiles")
    else:
        add("presets", "agent_required", "define semantic preview profiles", "profile names and data semantics are project-owned")
    if detection["seed"]["configured"]:
        add("seed", "auto", "reuse existing baseline seed contract")
    else:
        add("seed", "agent_required", "choose custom or schema-aware baseline seed", "DevSim cannot infer domain invariants")
    if detection["migrations"]["detected"] and detection["integration"] == "yes":
        add("lifecycle", "auto", "reuse configured lifecycle commands")
    else:
        add("lifecycle", "agent_required", "map DEV lifecycle commands", "DevSim cannot safely guess application startup or reset semantics")
    if detection["scenarios"]["count"]:
        add("runtime_scenario", "agent_required", "review or add canonical scenarios", "scenario actions require application-aware semantics")
    else:
        add("runtime_scenario", "agent_required", "create canonical scenarios", "scenario actions require application-aware semantics")
    if detection["browser"]["configured"]:
        add("observation", "auto", "reuse browser observation configuration")
    else:
        add("observation", "agent_required", "configure browser observation", "URL and selectors must be reviewed against the real application")
    agents_path = project_dir / "AGENTS.md"
    if agents_path.exists() and "devsim" in _read_text(agents_path).lower():
        add("agent_contract", "auto", "reuse repository DevSim guidance")
    else:
        add("agent_contract", "agent_required", "add the repository DevSim guidance snippet", "the integrating agent owns project-specific instructions")
    return {
        "ok": True,
        "operation": "onboard.plan",
        "project": inspection["project"],
        "integration": inspection["integration"],
        "steps": actions,
        "safe_to_apply": all(item["mode"] in {"auto", "agent_required"} for item in actions),
        "boundary": "DevSim plans and scaffolds contracts; the AI Agent owns application-aware integration.",
    }


def onboard_apply(project_dir: Path) -> dict[str, Any]:
    """Apply only the non-destructive standard scaffold."""
    plan = onboard_plan(project_dir)
    if any(item["mode"] == "user_required" for item in plan["steps"]):
        return {"ok": False, "operation": "onboard.apply", "status": "BLOCKED", "plan": plan, "errors": [{"code": "INVALID_MANIFEST", "detail": "existing devsim.yaml requires review before scaffold can be applied"}]}
    project_dir.mkdir(parents=True, exist_ok=True)
    detection = detect_project(project_dir)
    created: list[str] = []
    kept: list[str] = []

    def ensure_directory(relative: str) -> None:
        path = project_dir / relative
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        (kept if existed else created).append(relative)

    def ensure_file(relative: str, content: str) -> None:
        path = project_dir / relative
        if path.exists():
            kept.append(relative)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(relative)

    if not (project_dir / "devsim.yaml").exists():
        ensure_file("devsim.yaml", f"""version: 1
project:
  name: {project_dir.name}
environment:
  mode: development
database:
  engine: postgres
  lifecycle: {{}}
seed:
  mode: schema
  spec: devsim/seed.yaml
scenarios:
  path: devsim/scenarios
runtime:
  base_url: http://127.0.0.1:8000
  adapters:
    - type: http
    - type: command
presets:
  normal:
    seed_profile: normal
    scenario: normal
""")
    else:
        kept.append("devsim.yaml")

    if not detection["existing_devsim"]["directory"]:
        ensure_directory("devsim/")
    else:
        kept.append("devsim/")

    if not detection["seed"]["configured"] and not detection["existing_devsim"]["seed"]:
        ensure_file("devsim/seed.yaml", """# Generated seed specification. REVIEW_REQUIRED: define project-owned semantics.
mode: schema
schema:
  database_url: ${env.DEVSIM_DATABASE_URL}
plan:
  tables: {}
profiles:
  normal: {}
  minimal: {}
""")
    elif detection["existing_devsim"]["seed"]:
        kept.append("devsim/seed.yaml")

    if detection["scenarios"]["count"] == 0:
        ensure_directory("devsim/scenarios/")
        ensure_file("devsim/scenarios/normal.yaml", """# Generated skeleton. REVIEW_REQUIRED: add project-owned actions.
version: 1
name: normal
description: Representative normal preview state.
clock: {speed: 10}
runtime:
  mode: persistent
timeline: []
""")
    else:
        kept.append("devsim/scenarios/")

    scaffold = {
        "ok": True,
        "operation": "onboard.apply",
        "status": "SCAFFOLDED",
        "created": created,
        "kept": kept,
        "review_required": bool(created),
        "next_steps": [
            "review any generated scaffold and complete agent_required onboarding steps",
            "run devsim project validate --json",
            "run devsim doctor --json before preview",
        ],
    }
    return {"ok": True, "operation": "onboard.apply", "status": "SCAFFOLDED", "plan": plan, "scaffold": scaffold}


def onboard_validate(project_dir: Path) -> dict[str, Any]:
    """Aggregate existing validators into the onboarding qualification contract."""
    project_dir = project_dir.resolve()
    core = validate_project(project_dir)
    checks_by_name = {item["name"]: item for item in core.get("checks", [])}
    agent_text = _read_text(project_dir / "AGENTS.md").lower()
    agent_ok = "devsim" in agent_text and "project status" in agent_text
    browser_check = checks_by_name.get("browser", {})
    observation_ok = browser_check.get("status") == "PASS"
    checks = [
        {"name": "manifest", "status": checks_by_name.get("manifest", {}).get("status", "FAIL")},
        {"name": "lifecycle", "status": checks_by_name.get("lifecycle", {}).get("status", "FAIL")},
        {"name": "seed", "status": checks_by_name.get("seed", {}).get("status", "FAIL")},
        {"name": "scenarios", "status": checks_by_name.get("scenarios", {}).get("status", "FAIL")},
        {"name": "presets", "status": checks_by_name.get("presets", {}).get("status", "FAIL")},
        {"name": "observation", "status": "PASS" if observation_ok else "FAIL" if browser_check.get("status") == "FAIL" else "REVIEW_REQUIRED"},
        {"name": "agent_contract", "status": "PASS" if agent_ok else "REVIEW_REQUIRED"},
    ]
    required_pass = all(item["status"] == "PASS" for item in checks)
    return {
        "ok": required_pass,
        "operation": "onboard.validate",
        "integration": "READY" if required_pass else "PARTIAL" if core.get("status") != "INVALID" else "INVALID",
        "checks": checks,
        "project_validation": core,
        "errors": [] if required_pass else [{"code": "PROJECT_VALIDATION_FAILED", "detail": "onboarding qualification is incomplete"}],
    }
