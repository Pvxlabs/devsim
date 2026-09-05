from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, engine


if __name__ == "__main__":
    Base.metadata.drop_all(engine)
    print("database reset")
