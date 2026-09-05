from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import NotificationRecord, SessionLocal, SessionRecord


def main() -> None:
    seed = os.getenv("DEVSIM_SEED", "0")
    with SessionLocal() as db:
        db.add(SessionRecord(name=f"baseline-{seed}", status="created"))
        db.add(NotificationRecord(message=f"Baseline seeded with {seed}", status="created"))
        db.commit()
    print(f"seeded baseline with {seed}")


if __name__ == "__main__":
    main()
