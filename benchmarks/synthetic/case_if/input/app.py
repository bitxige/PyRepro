"""Input project for the complete-if controlled benchmark."""


def trigger() -> None:
    """Raise the strict target failure after removable branches."""
    diagnostics = False
    if diagnostics:
        raise RuntimeError("unreachable diagnostics")
    if 2 + 2 == 5:
        raise RuntimeError("unreachable arithmetic")
    if True:
        raise ValueError("if fixture failure")
