"""Run the Tactics2D controlled benchmark without pytest result capture.

This adapter deliberately imports and invokes the original test function from
the current candidate workspace. It does not recreate test setup or catch the
failure, so PyRepro's ExceptionOracle receives an ordinary Python traceback.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> None:
    """Load and invoke the benchmark test from the current workspace root."""
    workspace_root = Path.cwd().resolve()
    test_path = workspace_root / "tests" / "test_map_generator.py"
    sys.path.insert(0, str(workspace_root))

    spec = importlib.util.spec_from_file_location(
        "tactics2d_benchmark_test_map_generator", test_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load benchmark test module: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_intersection_asymmetric_arm_geometry()


if __name__ == "__main__":
    main()
