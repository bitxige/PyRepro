"""Provide unrelated observation ballast for the P3 fixture."""


def observation_name(index: int) -> str:
    """Return an unused observation name."""
    return f"observation-{index}"


class ObservationCache:
    """Represent unused observation cache state."""

    def empty(self) -> bool:
        """Return an unused cache state."""
        return True


async def read_observation() -> tuple[float, ...]:
    """Return an unused asynchronous observation."""
    return 0.0, 0.0


def merge_observations(
    left: tuple[str, ...], right: tuple[str, ...]
) -> tuple[str, ...]:
    """Return an unused merged observation sequence."""
    return left + right


class ObservationFormatter:
    """Represent unused observation formatting."""

    def format(self, values: tuple[float, ...]) -> str:
        """Return an unused observation string."""
        return ",".join(str(value) for value in values)
