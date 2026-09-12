"""Utility helpers for the sample project."""


def _is_blank(value: str) -> bool:
    return value is None or value.strip() == ""


def normalize_expression(value: str) -> str:
    """Return an expression with surrounding and regular spaces removed."""
    return value.strip().replace(" ", "")
