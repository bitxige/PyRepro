"""Standalone complete-if fixture for external reducer comparison."""


def trigger() -> None:
    """Raise the target failure after removable branches."""
    diagnostics = False
    if diagnostics:
        raise RuntimeError("unreachable diagnostics")
    if 2 + 2 == 5:
        raise RuntimeError("unreachable arithmetic")
    if True:
        raise ValueError("if fixture failure")


def test_trigger() -> None:
    """Exercise the target failure through a pytest-addressable node."""
    trigger()


test_trigger()
