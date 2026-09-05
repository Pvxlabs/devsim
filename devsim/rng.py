from __future__ import annotations

import random
import string


class DeterministicRNG:
    """A run-local RNG; no module-level random state is touched."""

    def __init__(self, seed: int):
        self.seed = seed
        self._random = random.Random(seed)

    def random(self) -> float:
        return self._random.random()

    def randint(self, start: int, end: int) -> int:
        return self._random.randint(start, end)

    def choice(self, values: list[str] | tuple[str, ...]) -> str:
        return self._random.choice(values)

    def token(self, length: int = 12) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(self._random.choice(alphabet) for _ in range(length))
