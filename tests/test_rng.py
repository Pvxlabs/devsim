from devsim.rng import DeterministicRNG


def test_rng_replays_without_global_state() -> None:
    first = DeterministicRNG(42)
    second = DeterministicRNG(42)
    assert [first.randint(0, 100), first.token(8), first.random()] == [second.randint(0, 100), second.token(8), second.random()]
