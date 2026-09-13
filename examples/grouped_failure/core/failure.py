"""Raise the failure preserved by the grouped-reduction benchmark."""


def trigger_failure(value: str) -> None:
    raise RuntimeError(f"grouped reduction failure: {value}")
