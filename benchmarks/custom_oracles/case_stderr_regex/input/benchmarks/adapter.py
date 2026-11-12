"""Trusted command entrypoint for the stderr-regex Oracle fixture."""

import sys
from pathlib import Path


def main() -> int:
    """Write the fixture-owned validation result to standard error."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from regression_test import test_stderr_failure

    print(test_stderr_failure(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
