#!/usr/bin/env python3
"""Print a small schema-seed benchmark using a caller-provided local database.

This intentionally measures generation/planning separately from PostgreSQL insert
time. It is a smoke benchmark, not a load-testing harness.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devsim.schema import ColumnModel, SchemaModel, TableModel
from devsim.seed import GeneratorRegistry, _build_row, build_seed_plan
from devsim.rng import DeterministicRNG


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", default="100,1000,10000")
    args = parser.parse_args()
    schema = SchemaModel((TableModel("rows", columns=(ColumnModel("id", "int4", False, primary_key=True), ColumnModel("value", "text", False))),))
    registry = GeneratorRegistry()
    for raw_count in args.counts.split(","):
        count = int(raw_count)
        config = {"mode": "schema", "plan": {"tables": {"rows": {"count": count, "columns": {"value": "string"}}}}}
        started = time.perf_counter()
        plan = build_seed_plan(schema, config)
        generated = {"rows": []}
        rng = DeterministicRNG(42)
        for index in range(count):
            generated["rows"].append(_build_row(schema.tables[0], plan.tables[0], generated, rng, index, registry))
        elapsed = time.perf_counter() - started
        print(f"rows={count} generation_and_plan_seconds={elapsed:.6f} estimated_rows={plan.estimated_rows}")


if __name__ == "__main__":
    main()
