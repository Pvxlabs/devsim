from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def main() -> None:
    seed = os.getenv("DEVSIM_SEED", "0")
    request = Request(
        "http://127.0.0.1:8000/api/demo/events",
        data=json.dumps({"type": f"generated_{seed}"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        print(response.read().decode())


if __name__ == "__main__":
    main()
