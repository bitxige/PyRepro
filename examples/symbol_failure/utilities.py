"""Provide unrelated utility ballast for the P3 fixture."""


def utility_name(value: str) -> str:
    """Return an unused utility name."""
    return value.strip().lower()


class UtilityPreview:
    """Represent unused utility preview behavior."""

    def show(self) -> str:
        """Return an unused preview."""
        return "utility"


async def read_utility() -> str:
    """Return an unused asynchronous utility result."""
    return "utility"


def utility_pairs(values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Return unused adjacent utility pairs."""
    return tuple(zip(values, values[1:]))
