"""Tests for the sample calculator project."""

from calculator import calculate_expression, describe_result


def test_calculate_expression():
    """Verify arithmetic and formatted calculator results."""
    assert calculate_expression("2+3") == 5
    assert calculate_expression("10 - 4 + 1") == 7
    assert describe_result("2+3") == "2+3 = 5"
