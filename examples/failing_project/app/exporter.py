"""Unrelated export ballast for the P0 reducer fixture."""


def export_identifier(identifier: str) -> dict[str, str]:
    """Build an export record for a lane identifier.

    Args:
        identifier: Lane identifier to export.

    Returns:
        Serializable export record.
    """
    return {"id": identifier}
