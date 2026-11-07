"""Trusted strict-oracle entrypoint for case_nested_list."""

import sys
from pathlib import Path


def main() -> None:
    """Run the fixture-owned failing regression test."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from regression_test import test_nested_list_failure

    test_nested_list_failure()


if __name__ == "__main__":
    main()
