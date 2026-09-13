"""Provide deterministic environment values for the P3 failure chain."""


def route_label(identifier: str) -> str:
    """Return an unused normalized route label."""
    normalized = identifier.strip().replace(" ", "-")
    return f"route:{normalized}"


class RoadPreview:
    """Represent unused road-preview metadata."""

    def lanes(self) -> int:
        """Return an unused lane count."""
        return 2


def summarize_surface(values: tuple[float, ...]) -> float:
    """Return an unused surface summary."""
    return sum(values) / len(values)


@staticmethod
def preview_weather() -> str:
    """Return an unused environment preview."""
    return "clear"


async def collect_observation_names() -> tuple[str, ...]:
    """Return unused asynchronous observation names."""
    return "speed", "heading"


class RoadDiagnostics:
    """Represent unused environment diagnostics."""

    def report(self) -> dict[str, str]:
        """Return an unused diagnostic report."""
        return {"road": "healthy"}


class RoadArtifactPlanner:
    """Represent unrelated artifact planning retained in the environment file."""

    def route_name(self, identifier: str) -> str:
        """Return an unused route-artifact name."""
        return identifier.strip().lower()

    def route_parts(self, identifier: str) -> tuple[str, ...]:
        """Return unused route-artifact parts."""
        name = self.route_name(identifier)
        return "road", name

    def route_path(self, identifier: str) -> str:
        """Return an unused route-artifact destination."""
        return "/".join(self.route_parts(identifier))

    def route_state(self) -> dict[str, str]:
        """Return unused route-artifact state."""
        return {"state": "new"}

    def route_samples(self, count: int) -> tuple[int, ...]:
        """Return unused route-artifact samples."""
        return tuple(range(count))

    def route_summary(self, count: int) -> str:
        """Return an unused route-artifact summary."""
        samples = self.route_samples(count)
        return f"samples={len(samples)}"

    def is_active(self) -> bool:
        """Return an unused route-artifact state."""
        return False

    def reset(self) -> None:
        """Perform an unused route-artifact reset."""
        return None


class RoadHistory:
    """Represent an independent history feature retained in the environment file."""

    def entry_name(self, index: int) -> str:
        """Return an unused road-history entry name."""
        return f"road-{index}"

    def entry_names(self, count: int) -> tuple[str, ...]:
        """Return unused road-history entry names."""
        return tuple(self.entry_name(index) for index in range(count))

    def newest_entry(self, count: int) -> str | None:
        """Return an unused newest road-history entry."""
        names = self.entry_names(count)
        return names[-1] if names else None

    def history_size(self, count: int) -> int:
        """Return an unused road-history size."""
        return len(self.entry_names(count))

    def history_state(self) -> dict[str, bool]:
        """Return unused road-history state."""
        return {"loaded": False}

    def clear_history(self) -> None:
        """Perform an unused road-history cleanup."""
        return None


def build_reward_inputs() -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return the incompatible error and weight vectors."""
    errors = (0.4, 0.2, 0.1, 0.3)
    weights = (0.25, 0.5, 0.25)
    return errors, weights
