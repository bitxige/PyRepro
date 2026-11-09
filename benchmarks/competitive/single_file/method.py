"""Standalone direct-method fixture for external reducer comparison."""


class Scenario:
    """Provide one required failure path and removable helper methods."""

    def render_preview(self) -> str:
        """Return an unrelated preview label."""
        return "preview"

    def calculate_margin(self, left: int, right: int) -> int:
        """Return unrelated arithmetic."""
        return left + right

    def archive_metadata(self) -> dict[str, str]:
        """Return unrelated archival metadata."""
        return {"status": "archived"}

    def trigger(self) -> None:
        """Raise the strict target failure."""
        raise ValueError("method fixture failure")


def test_trigger() -> None:
    """Exercise the target failure through a pytest-addressable node."""
    Scenario().trigger()


test_trigger()
