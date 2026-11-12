"""Business validation logic for the stdout-literal Oracle fixture."""


def unused_display_name() -> str:
    """Return removable presentation-only text."""
    return "checksum dashboard"


def compute_checksum(values: tuple[int, ...]) -> int:
    """Calculate the input checksum used by the validation rule."""
    return sum(values)


def validation_message(values: tuple[int, ...], expected: int) -> str:
    """Return a failure marker only when the business checksum disagrees."""
    observed = compute_checksum(values)
    if observed == expected:
        return "VALIDATION_OK"
    return "VALIDATION_FAILED: checksum mismatch"
