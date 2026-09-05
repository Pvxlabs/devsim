# AI Agent Workflow

The following workflow keeps an agent on the real application path:

1. Run `devsim doctor --json`.
2. Inspect `devsim seed plan --profile <profile> --json` before mutation.
3. Start the canonical preview with deterministic seed `42`.
4. Drive behavior through the application API or UI, not direct runtime-table inserts.
5. Verify state through the application API and, when configured, browser expectations.
6. Capture a screenshot when visual evidence is relevant.
7. Read `devsim status --json` and `devsim scenario inspect <run_id> --json`.
8. Stop the managed runtime when the task is complete.

Use another seed only when the task requires a different data shape. Keep generated
`.devsim/` artifacts out of commits. A missing browser dependency is an explicit
blocked observation result, not evidence of success.
