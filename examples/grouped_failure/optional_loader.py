"""Require optional modules to be either both present or both absent."""

from pathlib import Path


def configure_optional_pair() -> str:
    optional_root = Path(__file__).parent / "optional"
    has_a = (optional_root / "optional_a.py").is_file()
    has_b = (optional_root / "optional_b.py").is_file()
    if has_a != has_b:
        raise ImportError("optional pair must be complete")
    if not has_a:
        return "disabled"
    from optional.optional_a import optional_label as label_a
    from optional.optional_b import optional_label as label_b

    return label_a() + label_b()
