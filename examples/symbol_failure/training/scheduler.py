"""Provide unrelated scheduling ballast for the P3 fixture."""


def schedule_name(index: int) -> str:
    """Return an unused schedule name."""
    return f"schedule-{index}"


def schedule_window(start: int, stop: int) -> tuple[int, int]:
    """Return an unused schedule window."""
    return start, stop


class WarmupSchedule:
    """Represent an unused warmup schedule."""

    def value(self, step: int) -> float:
        """Return an unused warmup value."""
        return min(step / 10.0, 1.0)


async def read_schedule_state() -> str:
    """Return an unused asynchronous schedule state."""
    return "ready"


def summarize_schedule(names: tuple[str, ...]) -> str:
    """Return an unused schedule summary."""
    return ",".join(names)


class RetrySchedule:
    """Represent unused retry policy data."""

    def delays(self) -> tuple[int, ...]:
        """Return unused retry delays."""
        return 1, 2, 4
