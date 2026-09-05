from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine


if __name__ == "__main__":
    migration = Path(__file__).resolve().parents[1] / "migrations" / "001_initial.sql"
    with engine.begin() as connection:
        for statement in migration.read_text(encoding="utf-8").split(";"):
            statement = statement.strip()
            if statement and not statement.startswith("--"):
                connection.exec_driver_sql(statement)
    print("schema ready")
