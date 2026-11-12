"""Business validation logic for the stderr-regex Oracle fixture."""


def unused_category_label() -> str:
    """Return removable presentation-only text."""
    return "record diagnostics"


def payload_number(record: dict[str, object]) -> int:
    """Build a deterministic but non-literal payload identifier."""
    return 1000 + len(str(record["payload"]))


def validation_log(record: dict[str, object]) -> str:
    """Return an error-family log only when the record is invalid."""
    if record["valid"]:
        return "VALID_RECORD"
    return f"ERROR[PAYLOAD-{payload_number(record)}]: invalid record"
