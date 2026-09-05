"""Generic, read-only PostgreSQL schema inspection for preview tooling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from .errors import DevSimError
from .safety import assert_database_url_safe


class SchemaError(DevSimError):
    code = "schema_error"


@dataclass(frozen=True)
class ColumnModel:
    name: str
    data_type: str
    nullable: bool
    default: str | None = None
    primary_key: bool = False
    unique: bool = False
    enum_values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type,
            "nullable": self.nullable,
            "default": self.default,
            "primary_key": self.primary_key,
            "unique": self.unique,
            "enum_values": list(self.enum_values),
        }


@dataclass(frozen=True)
class ForeignKeyModel:
    column: str
    referenced_table: str
    referenced_column: str
    constraint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "referenced_table": self.referenced_table,
            "referenced_column": self.referenced_column,
            "constraint": self.constraint,
        }


@dataclass(frozen=True)
class TableModel:
    name: str
    schema: str = "public"
    columns: tuple[ColumnModel, ...] = ()
    foreign_keys: tuple[ForeignKeyModel, ...] = ()
    checks: tuple[str, ...] = ()

    @property
    def primary_keys(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.primary_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema,
            "columns": [column.to_dict() for column in self.columns],
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [foreign_key.to_dict() for foreign_key in self.foreign_keys],
            "checks": list(self.checks),
        }


@dataclass(frozen=True)
class SchemaModel:
    tables: tuple[TableModel, ...]
    warnings: tuple[str, ...] = ()

    @property
    def table_map(self) -> dict[str, TableModel]:
        return {table.name: table for table in self.tables}

    def dependency_graph(self) -> dict[str, tuple[str, ...]]:
        names = set(self.table_map)
        return {
            table.name: tuple(sorted({foreign_key.referenced_table for foreign_key in table.foreign_keys if foreign_key.referenced_table in names}))
            for table in self.tables
        }

    def dependency_order(self, selected: Iterable[str] | None = None) -> tuple[str, ...]:
        names = set(selected or self.table_map)
        unknown = sorted(names - set(self.table_map))
        if unknown:
            raise SchemaError(f"unknown table(s): {', '.join(unknown)}")
        graph = {name: {dependency for dependency in self.dependency_graph()[name] if dependency in names} for name in names}
        order: list[str] = []
        while graph:
            ready = sorted(name for name, dependencies in graph.items() if not dependencies)
            if not ready:
                cycle = ", ".join(sorted(graph))
                raise SchemaError(f"CYCLIC_SEED_DEPENDENCY: {cycle}")
            order.extend(ready)
            for name in ready:
                graph.pop(name)
            for dependencies in graph.values():
                dependencies.difference_update(ready)
        return tuple(order)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": [table.to_dict() for table in self.tables],
            "dependency_graph": {key: list(value) for key, value in self.dependency_graph().items()},
            "dependency_order": list(self.dependency_order()),
            "warnings": list(self.warnings),
        }


def inspect_postgres(database_url: str) -> SchemaModel:
    assert_database_url_safe(database_url)
    try:
        import psycopg
    except ImportError as exc:
        raise SchemaError("PostgreSQL inspection requires psycopg; install devsim[postgres]") from exc
    normalized_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(normalized_url) as connection:
            return _inspect_connection(connection)
    except SchemaError:
        raise
    except Exception as exc:
        raise SchemaError(f"could not inspect PostgreSQL schema: {exc}") from exc


def _inspect_connection(connection: Any) -> SchemaModel:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT table_schema, table_name FROM information_schema.tables
               WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema')
               ORDER BY table_schema, table_name"""
        )
        tables = [(str(row[0]), str(row[1])) for row in cursor.fetchall()]
        cursor.execute(
            """SELECT table_schema, table_name, column_name, data_type, is_nullable,
                      column_default, udt_name
               FROM information_schema.columns
               WHERE table_schema NOT IN ('pg_catalog','information_schema')
               ORDER BY table_schema, table_name, ordinal_position"""
        )
        columns = list(cursor.fetchall())
        cursor.execute(
            """SELECT tc.table_schema, tc.table_name, kcu.column_name, tc.constraint_type
               FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu USING (constraint_schema, constraint_name, table_schema, table_name)
               WHERE tc.constraint_type IN ('PRIMARY KEY','UNIQUE')
               ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position"""
        )
        key_rows = list(cursor.fetchall())
        cursor.execute(
            """SELECT tc.table_schema, tc.table_name, kcu.column_name,
                      ccu.table_name, ccu.column_name, tc.constraint_name
               FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu USING (constraint_schema, constraint_name, table_schema, table_name)
               JOIN information_schema.constraint_column_usage ccu
                 ON ccu.constraint_schema=tc.constraint_schema AND ccu.constraint_name=tc.constraint_name
               WHERE tc.constraint_type='FOREIGN KEY'
               ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position"""
        )
        foreign_keys = list(cursor.fetchall())
        cursor.execute(
            """SELECT n.nspname, c.relname, pg_get_constraintdef(con.oid)
               FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE con.contype='c' AND n.nspname NOT IN ('pg_catalog','information_schema')
               ORDER BY n.nspname, c.relname"""
        )
        checks = list(cursor.fetchall())
        return _model_from_rows(tables, columns, key_rows, foreign_keys, checks)


def _model_from_rows(
    tables: list[tuple[str, str]],
    columns: list[tuple[Any, ...]],
    key_rows: list[tuple[Any, ...]],
    foreign_keys: list[tuple[Any, ...]],
    checks: list[tuple[Any, ...]],
) -> SchemaModel:
    keys = {(str(row[0]), str(row[1]), str(row[2])): str(row[3]) for row in key_rows}
    grouped_columns: dict[tuple[str, str], list[ColumnModel]] = {}
    for schema, table, name, data_type, nullable, default, udt_name in columns:
        identity = (str(schema), str(table), str(name))
        grouped_columns.setdefault((str(schema), str(table)), []).append(
            ColumnModel(
                name=str(name),
                data_type=str(udt_name or data_type),
                nullable=str(nullable).upper() == "YES",
                default=str(default) if default is not None else None,
                primary_key=keys.get(identity) == "PRIMARY KEY",
                unique=keys.get(identity) == "UNIQUE",
            )
        )
    grouped_fks: dict[tuple[str, str], list[ForeignKeyModel]] = {}
    for schema, table, column, referenced_table, referenced_column, constraint in foreign_keys:
        grouped_fks.setdefault((str(schema), str(table)), []).append(
            ForeignKeyModel(str(column), str(referenced_table), str(referenced_column), str(constraint))
        )
    grouped_checks: dict[tuple[str, str], list[str]] = {}
    for schema, table, definition in checks:
        grouped_checks.setdefault((str(schema), str(table)), []).append(str(definition))
    result = tuple(
        TableModel(
            name=table,
            schema=schema,
            columns=tuple(grouped_columns.get((schema, table), [])),
            foreign_keys=tuple(grouped_fks.get((schema, table), [])),
            checks=tuple(grouped_checks.get((schema, table), [])),
        )
        for schema, table in tables
    )
    return SchemaModel(result)
