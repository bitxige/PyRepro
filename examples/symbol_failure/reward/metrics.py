"""Provide unrelated reward-metrics ballast for the P3 fixture."""


def metric_name(index: int) -> str:
    """Return an unused metric name."""
    return f"metric-{index}"


class MetricAccumulator:
    """Represent unused reward-metric accumulation."""

    def total(self, values: tuple[float, ...]) -> float:
        """Return an unused metric total."""
        return sum(values)


async def read_metric() -> float:
    """Return an unused asynchronous metric."""
    return 0.0


def format_metric(value: float) -> str:
    """Return an unused formatted metric."""
    return f"{value:.3f}"


class MetricWindow:
    """Represent unused metric-window data."""

    def bounds(self) -> tuple[int, int]:
        """Return unused metric-window bounds."""
        return 0, 1
