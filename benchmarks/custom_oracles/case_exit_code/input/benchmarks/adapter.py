"""Trusted command entrypoint for the exit-code Oracle fixture."""

import sys
from pathlib import Path


def main() -> int:
    """Execute the fixture-owned business validation."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from regression_test import test_exit_code_failure

    return test_exit_code_failure()


if __name__ == "__main__":
    sys.exit(main())
