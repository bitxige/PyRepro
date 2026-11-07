"""Trusted strict-oracle entrypoint for case_main_guard."""

import sys
from pathlib import Path


def main() -> None:
    """Run the fixture-owned failing regression test."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from regression_test import test_main_guard_failure

    test_main_guard_failure()


if __name__ == "__main__":
    main()
