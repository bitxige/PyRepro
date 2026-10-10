"""Tests for execution-verified batch import pruning."""

import json
import sys
from pathlib import Path

from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.import_pruner import BatchImportPruner
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_accepts_test_import_and_reexport_as_one_batch(tmp_path: Path):
    """A successful batch updates import and static __all__ together."""
    _project(tmp_path, "raise ValueError('target failure')")
    digest = tree_digest(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        ).prune(workspace)

        assert result.candidates_discovered == 2
        assert result.editable_operations == 2
        assert result.candidate_attempts == 1
        assert result.accepted_probes == 1
        assert result.executions == 5
        test_source = (workspace.root / "tests/test_target.py").read_text()
        assert "from pkg import Needed\n" in test_source
        initializer = (workspace.root / "pkg/__init__.py").read_text()
        assert "Ballast" not in initializer
        assert "__all__ = ['Needed']" in initializer
        assert result.probe_records[0].phase == "import_pruning"
        assert len(result.probe_records[0].candidate_descriptions) == 2
        assert result.source_unchanged

    assert tree_digest(tmp_path) == digest


def test_rejected_batch_restores_every_file_before_bounded_split(tmp_path: Path):
    """A rejected composite edit cannot leak into later probes or output."""
    _project(
        tmp_path,
        "assert globals()['Ballast'] is not None\n"
        "    raise ValueError('target failure')",
    )
    digest = tree_digest(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        ).prune(workspace)

        assert result.candidate_attempts == 3
        assert result.accepted_probes == 0
        assert result.rejected_probes == 3
        assert "Ballast" in (workspace.root / "tests/test_target.py").read_text()
        assert "Ballast" in (workspace.root / "pkg/__init__.py").read_text()
        assert result.source_unchanged

    assert tree_digest(tmp_path) == digest


def test_cli_writes_verified_pruned_project_and_import_probe_jsonl(
    tmp_path: Path, capsys
):
    """The public command emits import-pruning telemetry without file reduction."""
    source = tmp_path / "source"
    _project(source, "raise ValueError('target failure')")
    digest = tree_digest(source)
    output = tmp_path / "output"
    report = tmp_path / "probes.jsonl"

    status = main(
        [
            "prune-imports",
            str(source),
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--output",
            str(output),
            "--probe-records",
            str(report),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert status == 0
    assert "Import pruning:" in captured.out
    assert "Pruned project:" in captured.out
    assert (output / "tests/test_target.py").is_file()
    assert "from pkg import Needed\n" in (output / "tests/test_target.py").read_text(
        encoding="utf-8"
    )
    assert [record["phase"] for record in records] == ["import_pruning"]
    assert len(records[0]["candidate_details"]) == 2
    assert tree_digest(source) == digest


def _project(root: Path, target_body: str) -> None:
    _write(
        root,
        "pkg/__init__.py",
        "from .items import Needed, Ballast\n__all__ = ['Needed', 'Ballast']\n",
    )
    _write(
        root, "pkg/items.py", "class Needed:\n    pass\n\nclass Ballast:\n    pass\n"
    )
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "tests/test_target.py",
        "from pkg import Needed, Ballast\n\n"
        "def test_failure():\n"
        "    assert Needed is not None\n"
        f"    {target_body}\n\n"
        "def test_unrelated():\n"
        "    assert Ballast is not None\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
