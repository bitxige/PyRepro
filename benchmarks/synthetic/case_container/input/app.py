"""Input project for module-container controlled benchmarks."""

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
    """Raise the strict target failure while requiring two entries."""
    if SETTINGS["target"] == 7 and (13, 37) in POINTS:
        raise ValueError("container fixture failure")
    raise RuntimeError("required container data disappeared")
