# Schema-aware Seeding

Schema-aware seeding is an opt-in alternative to the existing custom `seed.command`
contract. It supports PostgreSQL only and is intended for development, preview,
and test databases.

## Contract

```yaml
seed:
  mode: schema
  schema:
    database_url: ${env.DEVSIM_DATABASE_URL}
  plan:
    tables:
      accounts:
        count: 10
        columns:
          email: {generator: internet.email}
          display_name: {generator: person.name}
      sessions:
        count: 30
        columns:
          status:
            choice: [active, completed, failed]
  profiles:
    minimal: {accounts: 1, sessions: 2}
    normal: {accounts: 10, sessions: 30}
```

The schema is authoritative for table structure and foreign keys. The seed plan is
authoritative for semantic values. Field names are not used to infer business
meaning.

## Preflight and mutation

```bash
devsim schema inspect --json
devsim seed plan --profile normal --json
devsim seed validate --profile normal --json
devsim seed --profile normal --seed 42
```

`plan` and `validate` do not insert rows. Seeding runs inside one transaction and
rolls back on any insert or constraint error. Database URLs are checked before a
connection is opened; production-looking hosts and database names are rejected.

The built-in generators are deterministic for a given seed. Foreign-key choices,
row order, and generated values therefore repeat for the same schema, plan, and
seed. Cyclic dependencies fail explicitly with `CYCLIC_SEED_DEPENDENCY`.
