# AI Agent Workflow

The following workflow keeps an agent on the real application path:

1. Discover capabilities with `devsim capabilities --json`.
2. Detect the repository with `devsim detect --json`.
3. Check integration completeness with `devsim project status --json`.
4. Run `devsim doctor --json`.
5. Inspect `devsim seed plan --profile <profile> --json` before mutation when schema-aware seeding is configured.
6. Start the canonical preview with deterministic seed `42`.
7. Drive behavior through the application API or UI, not direct runtime-table inserts.
8. Read `devsim preview status --json`, then inspect `devsim scenario inspect <run_id> --json`.
9. Capture a screenshot when visual evidence is relevant.
10. Stop the managed runtime with `devsim preview stop --json` when the task is complete.

Use another seed only when the task requires a different data shape. Keep generated
`.devsim/` artifacts out of commits. A missing browser dependency is an explicit
blocked observation result, not evidence of success.
