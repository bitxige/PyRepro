"""Unrelated metrics ballast for the P0 reducer fixture."""


def count_identifiers(identifiers: list[str]) -> int:
    """Return the number of identifiers.

    Args:
        identifiers: Identifiers to count.

    Returns:
        Number of supplied identifiers.
    """
    return len(identifiers)
