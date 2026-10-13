"""Tests for execution-verified batch import pruning."""

import ast
import json
import sys
from pathlib import Path

from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.budget import (
    BudgetExhaustedError,
    BudgetStopReason,
    OracleExecutionKind,
)
from pyrepro.reproducer.failure import FailureSignature
from pyrepro.reproducer.import_pruner import (
    BatchImportPruner,
    _apply,
    _Edit,
    _EditPlan,
    _Operation,
    _render_all_edit,
)
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest
from pyrepro.scanner.import_analyzer import ImportCandidate


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
        assert "from pkg import Needed\n\n\ndef test_failure" not in test_source
        initializer = (workspace.root / "pkg/__init__.py").read_text()
        assert initializer == "from .items import Needed\n__all__ = ['Needed']\n"
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


def test_budget_stop_during_an_import_probe_restores_unaccepted_edits(tmp_path: Path):
    """A deadline race after source edits cannot leak an unaccepted batch."""
    _project(tmp_path, "raise ValueError('target failure')")
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        ).prune(workspace, budget=_StopDuringProbeBudget(), verify_final=False)

        assert result.budget_exhausted
        assert result.candidate_attempts == 0
        assert "Ballast" in (workspace.root / "tests/test_target.py").read_text(
            encoding="utf-8"
        )
        assert "Ballast" in (workspace.root / "pkg/__init__.py").read_text(
            encoding="utf-8"
        )


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


def test_accepts_multiline_import_and_multiline_all_as_one_batch(tmp_path: Path):
    """A literal multiline import surface is edited atomically after one probe."""
    _multiline_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        ).prune(workspace)

        initializer = (workspace.root / "pkg/__init__.py").read_text(encoding="utf-8")
        test_source = (workspace.root / "tests/test_target.py").read_text(
            encoding="utf-8"
        )
        assert result.accepted_probes == 1
        assert "Ballast" not in initializer
        assert "from pkg import Needed" in test_source
        assert "from .items import Needed" in initializer
        assert "__all__ = ['Needed']" in initializer


def test_multiline_tuple_all_handles_alias_binding_name(tmp_path: Path):
    """An alias removes its exported name, not the imported source name."""
    _multiline_alias_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        result = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        ).prune(workspace)

        initializer = (workspace.root / "pkg/__init__.py").read_text(encoding="utf-8")
        assert result.accepted_probes == 1
        assert "PublicBallast" not in initializer
        assert "PublicNeeded" in initializer
        assert "Needed" in initializer
        assignment = ast.parse(initializer).body[1]
        assert isinstance(assignment, ast.Assign)
        assert isinstance(assignment.value, ast.Tuple)
        assert ast.literal_eval(assignment.value) == ("PublicNeeded",)


def test_all_edit_preserves_empty_tuple_and_list_container_types():
    """Canonical ``__all__`` rendering retains the original literal type."""
    tuple_source = "__all__ = ('Ballast',)\n"
    tuple_node = ast.parse(tuple_source).body[0]
    assert isinstance(tuple_node, ast.Assign)
    tuple_edit = _render_all_edit(tuple_source, tuple_node, {"Ballast"})
    assert tuple_edit is not None
    tuple_assignment = ast.parse(tuple_edit.replacement.decode("utf-8")).body[0]
    assert isinstance(tuple_assignment, ast.Assign)
    assert isinstance(tuple_assignment.value, ast.Tuple)
    assert ast.literal_eval(tuple_assignment.value) == ()

    list_source = "__all__ = ['Ballast']\n"
    list_node = ast.parse(list_source).body[0]
    assert isinstance(list_node, ast.Assign)
    list_edit = _render_all_edit(list_source, list_node, {"Ballast"})
    assert list_edit is not None
    list_assignment = ast.parse(list_edit.replacement.decode("utf-8")).body[0]
    assert isinstance(list_assignment, ast.Assign)
    assert isinstance(list_assignment.value, ast.List)
    assert ast.literal_eval(list_assignment.value) == []


def test_shared_multiline_all_reparses_after_accept_and_reject(tmp_path: Path):
    """Later probes use current ranges and restore only the rejected binding."""
    _shared_all_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        pruner = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=4
        )
        candidate_a, candidate_b, candidate_c = _shared_all_candidates()

        _, accepted_a = pruner._probe(
            workspace.root, (_Operation((candidate_a,)),), baseline, None
        )
        before_b = (workspace.root / "pkg/__init__.py").read_bytes()
        _, accepted_b = pruner._probe(
            workspace.root, (_Operation((candidate_b,)),), baseline, None
        )
        assert before_b == (workspace.root / "pkg/__init__.py").read_bytes()
        _, accepted_c = pruner._probe(
            workspace.root, (_Operation((candidate_c,)),), baseline, None
        )

        initializer = (workspace.root / "pkg/__init__.py").read_text(encoding="utf-8")
        assert accepted_a
        assert not accepted_b
        assert accepted_c
        assert initializer == "from .b import B\n__all__ = ['B']\n"


def test_shared_multiline_all_composes_multiple_reexports(tmp_path: Path):
    """One batch merges two removals into one shared ``__all__`` replacement."""
    _shared_all_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        candidate_a, _, candidate_c = _shared_all_candidates()

        _, accepted = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=1
        )._probe(
            workspace.root,
            (_Operation((candidate_a,)), _Operation((candidate_c,))),
            baseline,
            None,
        )

        assert accepted
        assert (workspace.root / "pkg/__init__.py").read_text(encoding="utf-8") == (
            "from .b import B\n__all__ = ['B']\n"
        )


def test_dynamic_all_mutation_is_a_safe_no_op(tmp_path: Path):
    """A later ``__all__.extend`` prevents source editing without mutation."""
    _shared_all_project(tmp_path)
    initializer_path = tmp_path / "pkg/__init__.py"
    initializer_path.write_text(
        f"{initializer_path.read_text(encoding='utf-8')}__all__.extend(['Extra'])\n",
        encoding="utf-8",
    )
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        candidate_a, _, _ = _shared_all_candidates()
        before = (workspace.root / "pkg/__init__.py").read_bytes()
        records, accepted, rejected, stopped = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=1
        )._search(
            workspace.root,
            (_Operation((candidate_a,)),),
            baseline,
            1,
            None,
        )

        assert records == []
        assert accepted == rejected == 0
        assert not stopped
        assert (workspace.root / "pkg/__init__.py").read_bytes() == before


def test_multitarget_all_assignment_is_a_safe_no_op(tmp_path: Path):
    """A second assignment target cannot be silently discarded by P7."""
    _shared_all_project(tmp_path)
    initializer_path = tmp_path / "pkg/__init__.py"
    initializer_path.write_text(
        initializer_path.read_text(encoding="utf-8").replace(
            "__all__ = [", "__all__ = exported_names = ["
        ),
        encoding="utf-8",
    )
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        candidate_a, _, _ = _shared_all_candidates()
        before = (workspace.root / "pkg/__init__.py").read_bytes()
        records, accepted, rejected, stopped = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=1
        )._search(
            workspace.root,
            (_Operation((candidate_a,)),),
            baseline,
            1,
            None,
        )

        assert records == []
        assert accepted == rejected == 0
        assert not stopped
        assert (workspace.root / "pkg/__init__.py").read_bytes() == before


def test_annotated_all_assignment_is_a_safe_no_op(tmp_path: Path):
    """P7 skips annotations until it can preserve module annotation semantics."""
    _shared_all_project(tmp_path)
    initializer_path = tmp_path / "pkg/__init__.py"
    initializer_path.write_text(
        initializer_path.read_text(encoding="utf-8").replace(
            "__all__ = [", "__all__: list[str] = ["
        ),
        encoding="utf-8",
    )
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        candidate_a, _, _ = _shared_all_candidates()
        before = (workspace.root / "pkg/__init__.py").read_bytes()
        records, accepted, rejected, stopped = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=1
        )._search(
            workspace.root,
            (_Operation((candidate_a,)),),
            baseline,
            1,
            None,
        )

        assert records == []
        assert accepted == rejected == 0
        assert not stopped
        assert (workspace.root / "pkg/__init__.py").read_bytes() == before


def test_partial_write_error_restores_every_planned_file(tmp_path: Path, monkeypatch):
    """An interrupted multi-file write restores the full pre-probe byte state."""
    first_path = tmp_path / "first.py"
    second_path = tmp_path / "second.py"
    first_path.write_bytes(b"accepted_before_probe = True\n")
    second_path.write_bytes(b"second_before_probe = True\n")
    originals = {path: path.read_bytes() for path in (first_path, second_path)}
    plan = _EditPlan(
        (
            ("first.py", (_Edit(0, 0, b"candidate_edit = True\n"),)),
            ("second.py", (_Edit(0, 0, b"candidate_edit = True\n"),)),
        )
    )
    original_write_bytes = Path.write_bytes
    failed = False
    writes: list[Path] = []

    def write_bytes_once(path: Path, data: bytes) -> int:
        nonlocal failed
        writes.append(path)
        if path == second_path and not failed:
            failed = True
            raise OSError("simulated second write failure")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes_once)

    try:
        _apply(tmp_path, plan)
    except OSError as error:
        assert str(error) == "simulated second write failure"
    else:
        raise AssertionError("partial write simulation did not raise OSError")

    assert writes[:2] == [first_path, second_path]
    assert first_path.read_bytes() == originals[first_path]
    assert second_path.read_bytes() == originals[second_path]


def test_multiline_edit_uses_utf8_byte_offsets_and_preserves_crlf(tmp_path: Path):
    """Non-ASCII text before a CRLF multiline candidate cannot shift its edit range."""
    _crlf_project(tmp_path)
    runner = CommandRunner([sys.executable, "run_target.py"], timeout_seconds=2)

    with ReductionWorkspace(tmp_path) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)
        assert baseline is not None
        candidate = ImportCandidate(
            kind="target_reexport",
            path="pkg/__init__.py",
            line=2,
            bound_name="Ballast",
            imported_module="pkg.items",
            imported_name="Ballast",
            reason="test",
            all_line=6,
        )
        _, accepted = BatchImportPruner(
            runner, "tests/test_target.py::test_failure", max_probes=1
        )._probe(workspace.root, (_Operation((candidate,)),), baseline, None)
        content = (workspace.root / "pkg/__init__.py").read_bytes()

        assert accepted
        assert content.startswith("说明 = '测试'\r\n".encode())
        assert b"\r\n" in content
        assert b"Ballast" not in content


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


def _multiline_project(root: Path) -> None:
    _write(
        root,
        "pkg/__init__.py",
        "from .items import (\n"
        "    Needed,\n"
        "    Ballast,\n"
        ")\n"
        "__all__ = [\n"
        "    'Needed',\n"
        "    'Ballast',\n"
        "]\n",
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
        "from pkg import (\n"
        "    Needed,\n"
        "    Ballast,\n"
        ")\n\n"
        "def test_failure():\n"
        "    assert Needed is not None\n"
        "    raise ValueError('target failure')\n\n"
        "def test_unrelated():\n"
        "    assert Ballast is not None\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _multiline_alias_project(root: Path) -> None:
    _write(
        root,
        "pkg/__init__.py",
        "from .items import (\n"
        "    Needed as PublicNeeded,\n"
        "    Ballast as PublicBallast,\n"
        ")\n"
        "__all__ = (\n"
        "    'PublicNeeded',\n"
        "    'PublicBallast',\n"
        ")\n",
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
        "from pkg import PublicNeeded, PublicBallast\n\n"
        "def test_failure():\n"
        "    assert PublicNeeded is not None\n"
        "    raise ValueError('target failure')\n\n"
        "def test_unrelated():\n"
        "    assert PublicBallast is not None\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _shared_all_project(root: Path) -> None:
    _write(
        root,
        "pkg/__init__.py",
        "from .a import A\n"
        "from .b import B\n"
        "from .c import C\n"
        "__all__ = [\n"
        "    'A',\n"
        "    'B',\n"
        "    'C',\n"
        "]\n",
    )
    _write(root, "pkg/a.py", "A = object()\n")
    _write(root, "pkg/b.py", "B = object()\n")
    _write(root, "pkg/c.py", "C = object()\n")
    _write(
        root,
        "run_target.py",
        "from pkg import B\nassert B is not None\nraise ValueError('target failure')\n",
    )


def _shared_all_candidates() -> tuple[
    ImportCandidate, ImportCandidate, ImportCandidate
]:
    return (
        ImportCandidate(
            kind="target_reexport",
            path="pkg/__init__.py",
            line=1,
            bound_name="A",
            imported_module="pkg.a",
            imported_name="A",
            reason="test",
            all_line=4,
        ),
        ImportCandidate(
            kind="target_reexport",
            path="pkg/__init__.py",
            line=2,
            bound_name="B",
            imported_module="pkg.b",
            imported_name="B",
            reason="test",
            all_line=4,
        ),
        ImportCandidate(
            kind="target_reexport",
            path="pkg/__init__.py",
            line=3,
            bound_name="C",
            imported_module="pkg.c",
            imported_name="C",
            reason="test",
            all_line=4,
        ),
    )


def _crlf_project(root: Path) -> None:
    initializer = (
        "说明 = '测试'\r\n"
        "from .items import (\r\n"
        "    Needed,\r\n"
        "    Ballast,\r\n"
        ")\r\n"
        "__all__ = [\r\n"
        "    'Needed',\r\n"
        "    'Ballast',\r\n"
        "]\r\n"
    )
    path = root / "pkg/__init__.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(initializer.encode("utf-8"))
    _write(
        root,
        "pkg/items.py",
        "class Needed:\n    pass\n\nclass Ballast:\n    pass\n",
    )
    _write(
        root,
        "run_target.py",
        "from pkg import Needed\nassert Needed is not None\n"
        "raise ValueError('target failure')\n",
    )


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _StopDuringProbeBudget:
    """Model a deadline that expires between a probe precheck and its launch."""

    def can_start_probe(self) -> bool:
        """Permit the outer stage loop to reach the probe mutation."""
        return True

    def ensure_can_start(self, kind: OracleExecutionKind) -> None:
        """Permit the pre-mutation check in this controlled race."""
        del kind

    def run_oracle(
        self,
        runner: CommandRunner,
        working_directory: Path,
        *,
        kind: OracleExecutionKind,
    ) -> ExecutionResult:
        """Stop exactly at the Oracle launch boundary."""
        if kind is OracleExecutionKind.BASELINE:
            return runner.run(working_directory)
        raise BudgetExhaustedError(BudgetStopReason.TIME_LIMIT)
