"""Minimal domain object required before the parser reaches its failure."""


class Lane:
    """Represent a parsed lane identifier.

    Args:
        identifier: Stable identifier supplied by the input record.
    """

    def __init__(self, identifier: str) -> None:
        """Store the lane identifier.

        Args:
            identifier: Stable lane identifier.
        """
        self.identifier = identifier
