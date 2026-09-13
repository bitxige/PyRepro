"""Provide unrelated reporting ballast for the P3 fixture."""


def report_title(name: str) -> str:
    """Return an unused report title."""
    return f"Report: {name}"


class ReportWriter:
    """Represent unused report writing behavior."""

    def write(self, content: str) -> str:
        """Return unused written content."""
        return content


async def build_report() -> str:
    """Return an unused asynchronous report."""
    return "report"


def report_sections() -> tuple[str, ...]:
    """Return unused report sections."""
    return "summary", "details"
