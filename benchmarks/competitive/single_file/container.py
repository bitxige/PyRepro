"""Standalone container fixture for external reducer comparison."""

SETTINGS = {
    "alpha": 1,
    "beta": 2,
    "gamma": 3,
    "target": 7,
    "delta": 4,
}

POINTS = [
    (1, 1),
    (2, 3),
    (5, 8),
    (13, 37),
    (21, 34),
]


def trigger() -> None:
    """Raise target failure while requiring two container entries."""
    if SETTINGS["target"] == 7 and (13, 37) in POINTS:
        raise ValueError("container fixture failure")
    raise RuntimeError("required container data disappeared")


def test_trigger() -> None:
    """Exercise the target failure through a pytest-addressable node."""
    trigger()


test_trigger()
