"""Business validation logic for the exit-code Oracle fixture."""


def format_debug_snapshot(payload: dict[str, object]) -> str:
    """Return removable diagnostic text unrelated to the decision."""
    return f"debug payload fields: {sorted(payload)}"


def checksum(values: tuple[int, ...]) -> int:
    """Return the deterministic checksum used by the validation rule."""
    return sum(values)


def validation_exit_code(payload: dict[str, object]) -> int:
    """Return 42 only when the payload retains the target invalid state."""
    value_checksum = checksum(tuple(payload["values"]))
    if payload["status"] != "invalid":
        return 0
    if value_checksum != 19:
        return 0
    return 42
