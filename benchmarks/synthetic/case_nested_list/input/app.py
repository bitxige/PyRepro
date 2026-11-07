"""Input project for the nested Palette-list controlled benchmark."""


class Palette:
    """Minimal palette object used by the supported nested-list stage."""

    def __init__(self, colors: list[tuple[int, int, int]]) -> None:
        """Store static RGB color entries."""
        self.colors = colors

    def require_target_color(self) -> None:
        """Raise the target failure only when the required tuple remains."""
        if (13, 37, 42) in self.colors:
            raise ValueError("nested palette fixture failure")
        raise RuntimeError("required palette color disappeared")


PALETTE = Palette(
    [
        (0, 0, 0),
        (13, 37, 42),
        (255, 255, 255),
        (9, 9, 9),
    ]
)


def trigger() -> None:
    """Exercise the palette's required failure path."""
    PALETTE.require_target_color()
