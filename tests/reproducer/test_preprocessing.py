"""Tests for verified import preprocessing followed by greedy file reduction."""

import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.preprocessing import PreprocessingFirstReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


@pytest.mark.parametrize("src_layout", (False, True))
def test_reuses_pruning_baseline_before_greedy_cleanup(
    tmp_path: Path, src_layout: bool
):
    """A target-unneeded import unlocks a subsequent file deletion."""
    source_prefix = Path("src") if src_layout else None
    _project(tmp_path, source_prefix)
    digest = tree_digest(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = PreprocessingFirstReducer(
            runner,
            "tests/test_target.py::test_failure",
            max_import_probes=4,
        ).reduce(workspace)

        assert result.import_pruning.baseline_runs == 3
        assert result.file_reduction.baseline_runs == 0
        assert result.executions == (
            result.import_pruning.executions + result.file_reduction.executions
        )
        assert result.source_unchanged
        assert not (workspace.root / (source_prefix or Path()) / "ballast.py").exists()
        assert "from ballast import Unneeded" not in (
            workspace.root / "tests/test_target.py"
        ).read_text(encoding="utf-8")
        assert {record.phase for record in result.probe_records} == {
            "import_pruning",
            "greedy",
        }

    assert tree_digest(tmp_path) == digest


def _project(root: Path, source_prefix: Path | None) -> None:
    source_directory = source_prefix or Path()
    _write(root, source_directory / "pkg/__init__.py", "from .needed import Needed\n")
    _write(root, source_directory / "pkg/needed.py", "class Needed:\n    pass\n")
    _write(root, source_directory / "ballast.py", "class Unneeded:\n    pass\n")
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "tests/test_target.py",
        "from ballast import Unneeded\nfrom pkg import Needed\n\n"
        "def test_failure():\n"
        "    assert Needed is not None\n"
        "    raise ValueError('target failure')\n\n"
        "def test_unrelated():\n"
        "    assert Unneeded is not None\n",
    )
    _write(
        root,
        "run_target.py",
        ("import sys\nsys.path.insert(0, 'src')\n" if source_prefix else "")
        + "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _write(root: Path, relative_path: str | Path, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
