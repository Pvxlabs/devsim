"""Schema-aware deterministic PostgreSQL seeding.

The module deliberately has no application-domain knowledge. A project supplies
semantic intent in ``seed.plan``; the database schema supplies structure and
the registry supplies deterministic value generators.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from .errors import DevSimError
from .models import Manifest
from .rng import DeterministicRNG
from .safety import assert_database_url_safe
from .schema import ColumnModel, SchemaModel, SchemaError, TableModel, inspect_postgres


class SeedError(DevSimError):
    code = "seed_error"


class SeedSchemaDriftError(SeedError):
    code = "SEED_SCHEMA_DRIFT"


class SeedTransactionError(SeedError):
    code = "SEED_TRANSACTION_ROLLBACK"


Generator = Callable[[DeterministicRNG, dict[str, Any], int], Any]


class GeneratorRegistry:
    def __init__(self) -> None:
        self._generators: dict[str, Generator] = {}
        for name, generator in _builtin_generators().items():
            self.register(name, generator)

    def register(self, name: str, generator: Generator) -> None:
        if not name or not callable(generator):
            raise SeedError("generator name and callable are required")
        self._generators[name] = generator

    def has(self, name: str) -> bool:
        return name in self._generators

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._generators))

    def generate(self, name: str, rng: DeterministicRNG, options: dict[str, Any], index: int) -> Any:
        try:
            return self._generators[name](rng, options, index)
        except KeyError as exc:
            raise SeedError(f"unknown generator {name!r}") from exc


@dataclass(frozen=True)
class TableSeedPlan:
    table: str
    count: int
    columns: dict[str, dict[str, Any]]
    dependencies: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "count": self.count,
            "columns": self.columns,
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True)
class SeedPlan:
    profile: str
    tables: tuple[TableSeedPlan, ...]
    estimated_rows: int
    warnings: tuple[str, ...] = ()

    @property
    def dependency_order(self) -> tuple[str, ...]:
        return tuple(item.table for item in self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "tables": [item.to_dict() for item in self.tables],
            "dependency_order": list(self.dependency_order),
            "estimated_rows": self.estimated_rows,
            "warnings": list(self.warnings),
        }


def schema_seed_config(manifest: Manifest) -> dict[str, Any]:
    config = dict(manifest.seed_config)
    if config.get("mode", "schema") != "schema":
        raise SeedError("seed configuration is not schema-aware (use the configured custom seed command)")
    return config


def database_url_for(manifest: Manifest) -> str:
    config = schema_seed_config(manifest)
    schema = config.get("schema") or {}
    if not isinstance(schema, dict):
        raise SeedError("seed.schema must be a mapping")
    value = schema.get("database_url") or manifest.database_url or os.environ.get("DEVSIM_DATABASE_URL")
    if not isinstance(value, str) or not value.strip():
        raise SeedError("schema-aware seeding requires seed.schema.database_url")
    value = _resolve_env_placeholder(value.strip())
    assert_database_url_safe(value)
    return value


def build_seed_plan(schema: SchemaModel, config: dict[str, Any], profile: str = "default", registry: GeneratorRegistry | None = None) -> SeedPlan:
    registry = registry or GeneratorRegistry()
    plan_data = config.get("plan") or {}
    if not isinstance(plan_data, dict):
        raise SeedError("seed.plan must be a mapping")
    tables_data = plan_data.get("tables") or {}
    if not isinstance(tables_data, dict):
        raise SeedError("seed.plan.tables must be a mapping")
    profiles = config.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise SeedError("seed.profiles must be a mapping")
    if profile != "default" and profile not in profiles:
        raise SeedError(f"seed profile {profile!r} was not found")
    profile_data = profiles.get(profile, {})
    if profile_data is None:
        profile_data = {}
    if not isinstance(profile_data, dict):
        raise SeedError(f"seed profile {profile!r} must be a mapping")
    table_map = schema.table_map
    selected = set(tables_data)
    unknown = sorted(selected - set(table_map))
    if unknown:
        raise SeedSchemaDriftError(f"SEED_SCHEMA_DRIFT: table(s) no longer exist: {', '.join(unknown)}")
    try:
        order = schema.dependency_order(selected)
    except SchemaError as exc:
        raise SeedError(str(exc)) from exc
    result: list[TableSeedPlan] = []
    warnings: list[str] = []
    for table_name in order:
        table = table_map[table_name]
        raw = tables_data[table_name]
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise SeedError(f"seed.plan.tables.{table_name} must be a mapping")
        count = _profile_count(profile_data, table_name, raw.get("count", 1))
        if count < 0:
            raise SeedError(f"seed count for {table_name!r} must be >= 0")
        columns = raw.get("columns", {}) or {}
        if not isinstance(columns, dict):
            raise SeedError(f"seed.plan.tables.{table_name}.columns must be a mapping")
        known_columns = {column.name for column in table.columns}
        drift = sorted(set(columns) - known_columns)
        if drift:
            raise SeedSchemaDriftError(f"SEED_SCHEMA_DRIFT: column(s) no longer exist on {table_name}: {', '.join(drift)}")
        normalized: dict[str, dict[str, Any]] = {}
        for column_name, declaration in columns.items():
            normalized[column_name] = _normalize_declaration(declaration, f"{table_name}.{column_name}", registry)
        for foreign_key in table.foreign_keys:
            if foreign_key.referenced_table not in selected:
                warnings.append(f"foreign key {table_name}.{foreign_key.column} references an unplanned table")
        result.append(TableSeedPlan(table_name, count, normalized, tuple(schema.dependency_graph()[table_name])))
    return SeedPlan(profile, tuple(result), sum(item.count for item in result), tuple(sorted(set(warnings))))


def inspect_seed_plan(manifest: Manifest, profile: str = "default") -> SeedPlan:
    config = schema_seed_config(manifest)
    return build_seed_plan(inspect_postgres(database_url_for(manifest)), config, profile)


def execute_seed(manifest: Manifest, *, seed: int, profile: str = "default", schema: SchemaModel | None = None) -> dict[str, Any]:
    config = schema_seed_config(manifest)
    database_url = database_url_for(manifest)
    schema = schema or inspect_postgres(database_url)
    plan = build_seed_plan(schema, config, profile)
    try:
        import psycopg
    except ImportError as exc:
        raise SeedError("PostgreSQL seeding requires psycopg; install devsim[postgres]") from exc
    normalized_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(normalized_url) as connection:
            result = _execute_connection(connection, schema, plan, seed)
    except SeedError:
        raise
    except Exception as exc:
        raise SeedTransactionError(f"SEED_TRANSACTION_ROLLBACK: {exc}") from exc
    return {"mode": "schema", "profile": profile, "seed": seed, **result}


def _execute_connection(connection: Any, schema: SchemaModel, plan: SeedPlan, seed: int) -> dict[str, Any]:
    rng = DeterministicRNG(seed)
    generated: dict[str, list[dict[str, Any]]] = {}
    inserted = 0
    try:
        with connection.cursor() as cursor:
            for table_plan in plan.tables:
                table = schema.table_map[table_plan.table]
                generated[table.name] = []
                for row_index in range(table_plan.count):
                    values = _build_row(table, table_plan, generated, rng, row_index)
                    columns = list(values)
                    sql = f"INSERT INTO {_quote_table(table.schema, table.name)} ({', '.join(_quote(name) for name in columns)}) VALUES ({', '.join('%s' for _ in columns)})"
                    if table.primary_keys:
                        sql += " RETURNING " + ", ".join(_quote(name) for name in table.primary_keys)
                    cursor.execute(sql, [values[column] for column in columns])
                    returned = cursor.fetchone() if table.primary_keys else None
                    if returned:
                        for key, value in zip(table.primary_keys, returned):
                            values[key] = value
                    generated[table.name].append(values)
                    inserted += 1
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise SeedTransactionError(f"SEED_TRANSACTION_ROLLBACK: {exc}") from exc
    return {"inserted_rows": inserted, "tables": {name: len(rows) for name, rows in generated.items()}}


def _build_row(
    table: TableModel,
    plan: TableSeedPlan,
    generated: dict[str, list[dict[str, Any]]],
    rng: DeterministicRNG,
    row_index: int,
    registry: GeneratorRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or GeneratorRegistry()
    declared = plan.columns
    foreign_keys = {foreign_key.column: foreign_key for foreign_key in table.foreign_keys}
    result: dict[str, Any] = {}
    for column in table.columns:
        declaration = declared.get(column.name)
        if declaration is not None:
            if "reference" in declaration:
                result[column.name] = _reference_value(declaration["reference"], generated, rng, column.name)
            else:
                generator = declaration.get("generator")
                options = declaration.get("options", {})
                result[column.name] = registry.generate(generator, rng, options, row_index)
            continue
        foreign_key = foreign_keys.get(column.name)
        if foreign_key and foreign_key.referenced_table in generated and generated[foreign_key.referenced_table]:
            result[column.name] = _reference_value({"table": foreign_key.referenced_table, "column": foreign_key.referenced_column}, generated, rng, column.name)
        elif column.default is not None or column.nullable:
            continue
        elif foreign_key:
            raise SeedError(
                f"SEED_SCHEMA_DRIFT: non-null foreign key {table.name}.{column.name} "
                f"references unplanned table {foreign_key.referenced_table!r}"
            )
        else:
            result[column.name] = _implicit_value(column, row_index, rng)
    return result


def _reference_value(reference: Any, generated: dict[str, list[dict[str, Any]]], rng: DeterministicRNG, field: str) -> Any:
    if not isinstance(reference, dict) or not isinstance(reference.get("table"), str):
        raise SeedError(f"{field}: reference must contain table and optional column")
    rows = generated.get(reference["table"], [])
    if not rows:
        raise SeedError(f"{field}: no generated rows available for reference {reference['table']!r}")
    selected = rows[rng.randint(0, len(rows) - 1)]
    column = reference.get("column") or next(iter(selected))
    if column not in selected:
        raise SeedError(f"{field}: referenced column {column!r} was not generated")
    return selected[column]


def _normalize_declaration(value: Any, field: str, registry: GeneratorRegistry) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"generator": value}
    elif isinstance(value, list):
        value = {"choice": value}
    if not isinstance(value, dict):
        raise SeedError(f"{field} must be a generator mapping")
    if "reference" in value:
        if len(value) != 1:
            raise SeedError(f"{field}: reference cannot be combined with generator")
        return {"reference": value["reference"]}
    if "choice" in value:
        choice = value["choice"]
        if not isinstance(choice, list) or not choice:
            raise SeedError(f"{field}.choice must be a non-empty list")
        return {"generator": "choice", "options": {"values": choice}}
    generator = value.get("generator")
    if not isinstance(generator, str) or not registry.has(generator):
        raise SeedError(f"{field}: unknown generator {generator!r}; available: {', '.join(registry.names())}")
    options = {key: item for key, item in value.items() if key != "generator"}
    return {"generator": generator, "options": options}


def _profile_count(profile_data: dict[str, Any], table: str, default: Any) -> int:
    value = profile_data.get(table, default)
    if isinstance(value, dict):
        value = value.get("count", default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SeedError(f"seed count for {table!r} must be an integer")
    return value


def _implicit_value(column: ColumnModel, row_index: int, rng: DeterministicRNG) -> Any:
    kind = column.data_type.lower()
    if kind in {"int2", "int4", "int8", "integer", "bigint", "smallint"}:
        return row_index + 1
    if "uuid" in kind:
        return rng.uuid()
    if kind in {"bool", "boolean"}:
        return bool(row_index % 2)
    if "timestamp" in kind or kind == "date":
        return _datetime_generator(rng, {}, row_index)
    return f"seed-{row_index + 1}"


def _builtin_generators() -> dict[str, Generator]:
    return {
        "integer": lambda rng, options, index: rng.randint(int(options.get("min", 0)), int(options.get("max", 100))),
        "float": lambda rng, options, index: rng.uniform(float(options.get("min", 0)), float(options.get("max", 1))),
        "boolean": lambda rng, options, index: bool(rng.randint(0, 1)),
        "uuid": lambda rng, options, index: rng.uuid(),
        "choice": lambda rng, options, index: rng.choice(tuple(options.get("values", options.get("choices", [])))),
        "sequence": lambda rng, options, index: int(options.get("start", 1)) + index * int(options.get("step", 1)),
        "datetime": _datetime_generator,
        "datetime.past": lambda rng, options, index: _datetime_generator(rng, {"past": True, **options}, index),
        "string": lambda rng, options, index: str(options.get("prefix", "seed-")) + rng.token(int(options.get("length", 10))),
        "email": lambda rng, options, index: f"user-{index}-{rng.token(8)}@example.test",
        "internet.email": lambda rng, options, index: f"user-{index}-{rng.token(8)}@example.test",
        "name": lambda rng, options, index: f"User {index + 1}",
        "person.name": lambda rng, options, index: f"User {index + 1}",
        "url": lambda rng, options, index: f"https://example.test/{rng.token(10)}",
    }


def _datetime_generator(rng: DeterministicRNG, options: dict[str, Any], index: int) -> str:
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    if options.get("past"):
        value = base - timedelta(days=rng.randint(0, 3650))
    else:
        value = base + timedelta(seconds=rng.randint(0, 3650 * 86400))
    return value.isoformat().replace("+00:00", "Z")


def _resolve_env_placeholder(value: str) -> str:
    match = re.fullmatch(r"\$\{(?:env\.)?([A-Za-z_][A-Za-z0-9_]*)\}", value)
    if match:
        try:
            return os.environ[match.group(1)]
        except KeyError as exc:
            raise SeedError(f"environment variable {match.group(1)!r} is not set") from exc
    placeholders = re.findall(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}", value)
    missing = sorted({name for name in placeholders if name not in os.environ})
    if missing:
        raise SeedError(f"environment variable(s) not set: {', '.join(missing)}")
    return re.sub(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}", lambda item: os.environ[item.group(1)], value)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_table(schema: str, table: str) -> str:
    return f"{_quote(schema)}.{_quote(table)}"
