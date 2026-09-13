"""Parse lane records for the P0 deterministic failure fixture."""

from app.model import Lane


def parse_lane(record: dict[str, str]) -> Lane:
    """Build a lane after reading its required width.

    Args:
        record: Lane record with required ``id`` and ``width`` values.

    Returns:
        Parsed lane object.
    """
    lane = Lane(record["id"])
    lane.width = record["width"]
    return lane
