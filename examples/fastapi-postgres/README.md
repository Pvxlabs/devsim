# FastAPI + PostgreSQL example

This example demonstrates DevSim against a real FastAPI process and PostgreSQL database. It uses generic sessions, events, and notifications so the example remains useful as a starting point for other stateful applications.

From this directory:

```bash
pip install -r requirements.txt
devsim up
devsim reset --seed 42
devsim scenario run active-session --seed 42
curl http://127.0.0.1:8000/api/demo/state
devsim down
```

The canonical managed preview path is:

```bash
devsim preview normal --seed 42 --json
devsim preview status --json
devsim preview stop --json
```

`normal` is a persistent preview profile. `active-session` remains a finite
foreground scenario for focused scenario testing.

The database lifecycle commands are intentionally ordinary project commands. The migration script applies the SQL in `migrations/001_initial.sql`; replace it with Alembic, Django migrations, or another migration tool without changing the DevSim contract.
