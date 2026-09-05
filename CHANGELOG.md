# Changelog

## 0.2.0

### Agent-native integration

- added read-only project discovery with `devsim detect` and capability discovery with `devsim capabilities`
- added integration completeness and validation commands with `devsim project status` and `devsim project validate`
- added product bootstrap flows with `devsim init --dry-run`, `devsim init --inspect`, and `devsim quickstart`
- added canonical preview readback and graceful shutdown with `devsim preview status` and `devsim preview stop`
- standardized machine-readable error envelopes and exit codes for agent callers
- added the DevSim Project Integration Standard v1 and agent workflow contract
- added the repository-owned Codex Skill and `devsim skill install`
- added CI guidance, GitHub Actions validation, and a portable integration template

## 0.1.0

- deterministic runtime with virtual time and seeded execution
- persistent scenarios and scenario composition
- HTTP and command adapters
- schema-aware PostgreSQL seeding
- preview presets with a local control API/UI
- browser observation and screenshot artifacts
- deterministic scenario replay
- AI-agent-friendly CLI and JSON workflow
