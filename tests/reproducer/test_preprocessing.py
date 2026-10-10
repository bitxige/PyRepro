"""Tests for verified import preprocessing followed by greedy file reduction."""

import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.coarse_reducer import CoarseFileReducer
from pyrepro.reproducer.failure import (
    FailureMatchMode,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.import_pruner import BatchImportPruner
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
        assert result.coarse_reduction is None
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


def test_coarse_budget_and_rejected_group_preserve_workspace(tmp_path: Path):
    """Accepted groups persist while rejected required packages are restored."""
    _project(tmp_path, None)
    digest = tree_digest(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = PreprocessingFirstReducer(
            runner, "tests/test_target.py::test_failure", max_coarse_probes=2
        ).reduce(workspace)

        assert result.coarse_reduction is not None
        assert result.coarse_reduction.candidate_attempts == 2
        assert result.coarse_reduction.accepted_probes == 1
        assert result.coarse_reduction.rejected_probes == 1
        assert not (workspace.root / "ballast.py").exists()
        assert (workspace.root / "pkg/needed.py").is_file()
        assert (workspace.root / "tests/test_target.py").is_file()
        coarse_records = result.coarse_reduction.probe_records
        assert [record.phase for record in coarse_records] == [
            "coarse_group",
            "coarse_group",
        ]
        assert coarse_records[1].exception_type in {
            "ImportError",
            "ModuleNotFoundError",
        }
        assert "greedy" in {record.phase for record in result.probe_records}
        assert len(result.probe_records) == (
            result.import_pruning.candidate_attempts
            + result.coarse_reduction.candidate_attempts
            + result.file_reduction.candidate_attempts
        )

    assert tree_digest(tmp_path) == digest


def test_coarse_rejects_parent_then_removes_optional_child(tmp_path: Path):
    """A rejected package can be split to remove an optional child directory."""
    _nested_project(tmp_path)
    digest = tree_digest(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        pruning = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=2
        ).prune(workspace)
        coarse = CoarseFileReducer(runner, max_probes=12).reduce(
            workspace,
            pruning.baseline_signature,
            FailureMatchMode.STRICT,
            pytest_node="tests/test_target.py::test_failure",
        )

        parent = next(
            record
            for record in coarse.probe_records
            if set(record.candidate_paths)
            == {
                "package/__init__.py",
                "package/optional/ballast.py",
                "package/required.py",
            }
        )
        optional_child = next(
            record
            for record in coarse.probe_records
            if record.candidate_paths == ("package/optional/ballast.py",)
        )
        assert not parent.accepted
        assert parent.phase == "coarse_group"
        assert optional_child.accepted
        assert optional_child.phase == "coarse_split"
        assert (workspace.root / "package/required.py").is_file()
        assert not (workspace.root / "package/optional/ballast.py").exists()
        assert (
            classify_result(
                runner.run(workspace.root),
                pruning.baseline_signature,
                workspace.root,
                FailureMatchMode.STRICT,
            )
            is ReductionOutcome.SAME_FAILURE
        )

    assert tree_digest(tmp_path) == digest


def test_pipeline_continues_when_import_analysis_has_no_editable_operations(
    tmp_path: Path,
):
    """No import candidates leaves a valid workspace for coarse and greedy stages."""
    _target_only_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = PreprocessingFirstReducer(
            runner, "tests/test_target.py::test_failure", max_coarse_probes=1
        ).reduce(workspace)

        assert result.import_pruning.editable_operations == 0
        assert result.import_pruning.candidate_attempts == 0
        assert result.coarse_reduction is not None
        assert result.coarse_reduction.candidate_attempts == 1
        assert result.coarse_reduction.probe_records[0].phase == "coarse_group"
        assert result.file_reduction.baseline_runs == 0


def test_rejected_import_batches_leave_original_workspace_for_coarse(tmp_path: Path):
    """Coarse probes start from imports restored after every rejected batch."""
    _rejected_import_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = PreprocessingFirstReducer(
            runner,
            "tests/test_target.py::test_failure",
            max_import_probes=4,
            max_coarse_probes=1,
        ).reduce(workspace)

        assert result.import_pruning.accepted_probes == 0
        assert result.import_pruning.rejected_probes > 0
        assert "Ballast" in (workspace.root / "tests/test_target.py").read_text(
            encoding="utf-8"
        )
        assert result.coarse_reduction is not None
        assert result.coarse_reduction.probe_records[0].exception_type in {
            "ImportError",
            "ModuleNotFoundError",
        }
        assert result.file_reduction.baseline_runs == 0


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


def _nested_project(root: Path) -> None:
    _write(root, "package/__init__.py", "from .required import required\n")
    _write(root, "package/required.py", "def required():\n    return True\n")
    _write(root, "package/optional/ballast.py", "VALUE = 1\n")
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "tests/test_target.py",
        "from package import required\n\n"
        "def test_failure():\n"
        "    assert required()\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _target_only_project(root: Path) -> None:
    _write(root, "pkg/__init__.py", "from .needed import Needed\n")
    _write(root, "pkg/needed.py", "class Needed:\n    pass\n")
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "tests/test_target.py",
        "from pkg import Needed\n\n"
        "def test_failure():\n"
        "    assert Needed is not None\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _rejected_import_project(root: Path) -> None:
    _write(
        root,
        "pkg/__init__.py",
        "from .items import Needed, Ballast\n__all__ = ['Needed', 'Ballast']\n",
    )
    _write(
        root,
        "pkg/items.py",
        "class Needed:\n    pass\n\nclass Ballast:\n    pass\n",
    )
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "tests/test_target.py",
        "from pkg import Needed, Ballast\n\n"
        "def test_failure():\n"
        "    assert Needed is not None\n"
        "    assert globals()['Ballast'] is not None\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _write(root: Path, relative_path: str | Path, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
