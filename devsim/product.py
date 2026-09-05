"""Read-only productization helpers for project discovery and validation."""

from __future__ import annotations

import json
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


def _database_detection(project_dir: Path, manifest: Manifest | None, manifest_error: Exception | None) -> dict[str, Any]:
    if manifest is not None:
        return {"engine": manifest.database_engine, "confidence": "high", "source": "devsim.yaml"}
    haystack = "\n".join(
        _read_text(project_dir / name).lower()
        for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "package.json", "docker-compose.yml", "compose.yml", "Dockerfile")
    )
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
    for name in ("docker-compose.yml", "compose.yml"):
        text = _read_text(project_dir / name)
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
    project_detected = project_dir.is_dir() and any((project_dir / marker).exists() for marker in ("devsim.yaml", "pyproject.toml", "package.json", "docker-compose.yml", "compose.yml", "Dockerfile", "AGENTS.md", "devsim"))
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
        for name, page in pages.items():
            path = page.get("path") if isinstance(page, dict) else page
            if not isinstance(path, str) or not path:
                browser_errors.append(f"{name}: page path is required")
            else:
                try:
                    assert_observation_url_safe(urljoin(manifest.base_url.rstrip("/") + "/", path.lstrip("/")))
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
