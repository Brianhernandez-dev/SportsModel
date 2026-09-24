# Disposable PostgreSQL test safety

Destructive database fixtures must never use normal SportsModel application
configuration. They require a dedicated disposable PostgreSQL target and refuse
to connect until all configuration-only checks pass.

The required test-only environment is:

- `SPORTSMODEL_TEST_DATABASE_URL`: explicit loopback URL with host, non-5432
  port, generated database name, and `sportsmodel_test` user;
- `SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB=1`: explicit destructive-test opt-in;
- `SPORTSMODEL_TEST_DATABASE_MARKER`: a generated 32-128 character token;
- `SPORTSMODEL_TEST_DATABASE_INSTANCE_ID`: the full 64-character Docker
  container ID;
- `SPORTSMODEL_PRODUCTION_DATABASE_SYSTEM_IDENTIFIER`: the current native
  production cluster system identifier, used only as an explicit deny identity.

Generated database names must match `sportsmodel_test_<12-32 lowercase hex>`.
Port 5432 and database `sportsmodel` are unconditionally refused. The test URL
must not overlap either `DATABASE_URL` or a complete application
`POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DB` identity. The guard does not load
`.env` or `SPORTSMODEL_ENV_FILE` and has no application-database fallback.

## In-server disposable marker

The generated database must contain one marker row outside `public`, so resetting
`public` does not erase the safety identity:

```sql
CREATE SCHEMA sportsmodel_test_guard;
CREATE TABLE sportsmodel_test_guard.instance_identity (
    marker text PRIMARY KEY,
    instance_id text NOT NULL UNIQUE,
    system_identifier text NOT NULL UNIQUE
);
INSERT INTO sportsmodel_test_guard.instance_identity (
    marker, instance_id, system_identifier
)
SELECT '<generated marker>', '<full Docker container ID>', system_identifier::text
FROM pg_control_system();
```

Immediately before `DROP SCHEMA public CASCADE`, the fixture verifies on the
same connection:

- resolved test host and published port;
- exact database and user;
- PostgreSQL version and non-recovery state;
- PostgreSQL cluster system identifier;
- inequality with the explicitly supplied production cluster system identifier;
- exact disposable marker;
- exact Docker container ID;
- marker system identifier equality with the connected cluster.

Only the marker digest—not the marker token or database password—is logged.
The log also records the non-secret resolved target and server identities.

## Destructive-path inventory

`tests/database/conftest.py` is the only repository test path that drops or
recreates a schema. All integration tests that use
`initialized_nfl_test_database` therefore pass through the central guard.
`test_mlb_completeness_postgres.py` does not reset a schema and rolls back its
data, but it also uses the central verified connection to prevent accidental
production writes.

The native backup/restore acceptance script is a separate operator workflow,
not test-fixture routing. Its create/restore/drop actions already require an
action-specific approval, a timestamped `sportsmodel_restore_acceptance_*`
database name, the expected owner, and its own database marker before restore or
drop. It is intentionally not routed through this Docker test guard.
