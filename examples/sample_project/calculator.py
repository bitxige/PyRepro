"""Small calculator example for RepoSentinel tests."""

from utils import _is_blank


def calculate_expression(expression: str, strict: bool = False) -> float:
    if _is_blank(expression):
        if strict:
            raise ValueError("expression cannot be blank")
        return 0.0
    total = 0.0
    current = ""
    sign = 1
    for character in expression:
        if character.isdigit() or character == ".":
            current += character
        elif character in "+-":
            if not current:
                raise ValueError("operator without a number")
            total += sign * float(current)
            current = ""
            sign = 1 if character == "+" else -1
        elif not character.isspace():
            raise ValueError(f"unexpected character: {character}")
    if not current:
        raise ValueError("expression must end with a number")
    return total + sign * float(current)


def describe_result(expression: str, strict: bool = False) -> str:
    """Format the result of an expression for display."""
    value = calculate_expression(expression, strict=strict)
    return f"{expression} = {value:g}"
