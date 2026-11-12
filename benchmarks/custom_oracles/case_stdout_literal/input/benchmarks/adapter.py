"""Trusted command entrypoint for the stdout-literal Oracle fixture."""

import sys
from pathlib import Path


def main() -> int:
    """Print the fixture-owned validation result and complete normally."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from regression_test import test_stdout_failure

    print(test_stdout_failure())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
