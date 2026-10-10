"""Regression coverage for the three-strategy benchmark driver."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from pyrepro.reproducer.failure import FailureSignature
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult
from pyrepro.reproducer.workspace import tree_digest

REPOSITORY_ROOT = Path(__file__).parents[2]
DRIVER = REPOSITORY_ROOT / "benchmarks" / "compare_preprocessing_strategies.py"


def test_driver_reports_comparable_verified_strategies(tmp_path: Path) -> None:
    """The small fixture exercises all configurations without source mutation."""
    source = tmp_path / "source"
    _write_fixture(source)
    digest = tree_digest(source)

    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            str(source),
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--coarse-probes",
            "2",
            "--",
            sys.executable,
            "run_target.py",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    strategies = {item["name"]: item for item in report["strategies"]}
    assert set(strategies) == {
        "blind_greedy",
        "import_then_greedy",
        "import_coarse_then_greedy",
    }
    for strategy in strategies.values():
        assert strategy["status"] == "passed"
        assert strategy["final_verification_passed"]
        assert strategy["source_unchanged"]
        assert strategy["independent_verification_executions"] == 3
        assert strategy["total_oracle_executions"] == (
            strategy["reducer_oracle_executions"] + 3
        )
        assert (
            sum(strategy["phase_executions"].values())
            == strategy["reducer_oracle_executions"]
        )
        assert strategy["baseline_failure_signature"] == {
            "exception_type": "ValueError",
            "file": "tests/test_target.py",
            "function": "test_failure",
            "normalized_message": "target failure",
        }
        assert [item["outcome"] for item in strategy["independent_verifications"]] == [
            "same_failure",
            "same_failure",
            "same_failure",
        ]

    assert report["provenance"]["source"]["commit"] is None
    assert report["provenance"]["source"]["dirty"] is None
    assert report["provenance"]["failure_match_mode"] == "strict"
    assert strategies["blind_greedy"]["max_import_probes"] is None
    assert strategies["blind_greedy"]["max_coarse_probes"] is None
    assert strategies["import_then_greedy"]["max_coarse_probes"] == 0
    assert strategies["import_coarse_then_greedy"]["max_coarse_probes"] == 2
    assert strategies["blind_greedy"]["phase_probe_counts"]["greedy"] > 0
    assert "import_pruning" in strategies["import_then_greedy"]["phase_probe_counts"]
    assert (
        "coarse_group" in strategies["import_coarse_then_greedy"]["phase_probe_counts"]
    )
    assert (
        strategies["import_then_greedy"]["remaining_python_lines"]
        < strategies["blind_greedy"]["remaining_python_lines"]
    )
    assert (
        strategies["import_coarse_then_greedy"]["remaining_python_lines"]
        <= strategies["import_then_greedy"]["remaining_python_lines"]
    )
    assert tree_digest(source) == digest


def test_independent_verification_records_actual_nonmatching_results(
    tmp_path: Path,
) -> None:
    """Different failures and unsupported results are never reported as baseline."""
    driver = _driver_module()
    baseline = FailureSignature(
        exception_type="ValueError",
        normalized_message="target failure",
        file="target.py",
        function="fail",
    )
    runner = _SequenceRunner(
        (
            _failure_result(tmp_path, "ValueError", "target failure"),
            _failure_result(tmp_path, "TypeError", "different failure"),
            ExecutionResult(("python", "run.py"), 1, "", "process aborted", False),
        )
    )

    observations = driver._independent_verifications(runner, tmp_path, baseline)

    assert [observation.outcome for observation in observations] == [
        "same_failure",
        "different_failure",
        "different_failure",
    ]
    assert observations[0].failure_signature == {
        "exception_type": "ValueError",
        "normalized_message": "target failure",
        "file": "target.py",
        "function": "fail",
    }
    assert observations[1].failure_signature["exception_type"] == "TypeError"
    assert observations[2].failure_signature is None


def test_reducer_exception_becomes_failed_strategy_record(
    tmp_path: Path, monkeypatch
) -> None:
    """A reducer exception cannot be emitted as a successful benchmark result."""
    driver = _driver_module()
    source = tmp_path / "source"
    _write_fixture(source)

    class FailingGreedy:
        """Stand-in that isolates driver failure reporting from reducer behavior."""

        def __init__(self, *args, **kwargs) -> None:
            pass

        def reduce(self, workspace) -> None:
            raise RuntimeError("intentional benchmark failure")

    monkeypatch.setattr(driver, "GreedyFileReducer", FailingGreedy)
    result = driver._run_strategy(
        "blind_greedy",
        source,
        CommandRunner((sys.executable, "run_target.py"), timeout_seconds=2),
        argparse.Namespace(
            expect=None,
            pytest_node="tests/test_target.py::test_failure",
            import_probes=16,
            coarse_probes=16,
        ),
        tree_digest(source),
    )

    assert result.status == "failed"
    assert result.error_type == "RuntimeError"
    assert result.final_verification_passed is False
    assert result.baseline_failure_signature is None
    assert result.total_oracle_executions is None


def test_snapshot_mismatch_after_first_strategy_skips_later_strategies(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A source change in A prevents B and C from using a new snapshot."""
    driver = _driver_module()
    source = tmp_path / "source"
    _write_fixture(source)
    calls: list[str] = []

    def mutate_first_strategy(name, source, runner, args, source_snapshot):
        calls.append(name)
        (source / "unexpected_change.py").write_text("changed = True\n")
        return _strategy_record(driver, name, status="failed", source_unchanged=False)

    monkeypatch.setattr(driver, "_run_strategy", mutate_first_strategy)

    exit_code = driver.main(_driver_argv(source))
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert calls == ["blind_greedy"]
    assert [item["status"] for item in report["strategies"]] == [
        "failed",
        "skipped",
        "skipped",
    ]
    for item in report["strategies"][1:]:
        assert item["error_type"] == "SourceSnapshotMismatch"
        assert item["initial_python_files"] is None
        assert item["remaining_python_files"] is None
        assert item["baseline_failure_signature"] is None
        assert item["total_oracle_executions"] is None


def test_snapshot_mismatch_after_second_strategy_skips_only_third(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A source change in B cannot affect C's benchmark input."""
    driver = _driver_module()
    source = tmp_path / "source"
    _write_fixture(source)
    calls: list[str] = []

    def mutate_second_strategy(name, source, runner, args, source_snapshot):
        calls.append(name)
        if name == "import_then_greedy":
            (source / "unexpected_change.py").write_text("changed = True\n")
            return _strategy_record(
                driver, name, status="failed", source_unchanged=False
            )
        return _strategy_record(driver, name, status="passed", source_unchanged=True)

    monkeypatch.setattr(driver, "_run_strategy", mutate_second_strategy)

    exit_code = driver.main(_driver_argv(source))
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert calls == ["blind_greedy", "import_then_greedy"]
    assert [item["status"] for item in report["strategies"]] == [
        "passed",
        "failed",
        "skipped",
    ]
    assert report["strategies"][2]["total_oracle_executions"] is None


def test_ordinary_strategy_failure_does_not_skip_later_strategies(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Only a snapshot mismatch blocks independent later strategies."""
    driver = _driver_module()
    source = tmp_path / "source"
    _write_fixture(source)
    calls: list[str] = []

    def fail_without_source_change(name, source, runner, args, source_snapshot):
        calls.append(name)
        status = "failed" if name == "blind_greedy" else "passed"
        return _strategy_record(driver, name, status=status, source_unchanged=True)

    monkeypatch.setattr(driver, "_run_strategy", fail_without_source_change)

    exit_code = driver.main(_driver_argv(source))
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert calls == [
        "blind_greedy",
        "import_then_greedy",
        "import_coarse_then_greedy",
    ]
    assert [item["status"] for item in report["strategies"]] == [
        "failed",
        "passed",
        "passed",
    ]


def _driver_argv(source: Path) -> list[str]:
    """Return a minimal valid driver argument vector for main-level tests."""
    return [
        str(source),
        "--pytest-node",
        "tests/test_target.py::test_failure",
        "--",
        sys.executable,
        "run_target.py",
    ]


def _strategy_record(
    driver,
    name: str,
    *,
    status: str,
    source_unchanged: bool,
):
    """Build a minimal fake strategy record for main-level control-flow tests."""
    passed = status == "passed"
    return driver.StrategyComparison(
        name=name,
        status=status,
        error_type=None if passed else "RuntimeError",
        error_message=None if passed else "simulated strategy failure",
        max_import_probes=None,
        max_coarse_probes=None,
        initial_python_files=1 if passed else None,
        initial_python_lines=1 if passed else None,
        remaining_python_files=1 if passed else None,
        remaining_python_lines=1 if passed else None,
        baseline_failure_signature=None,
        phase_executions={"greedy": 1} if passed else {},
        phase_probe_counts={"greedy": 1} if passed else {},
        phase_accepted_probes={"greedy": 1} if passed else {},
        reducer_oracle_executions=1 if passed else None,
        independent_verification_executions=3 if passed else 0,
        total_oracle_executions=4 if passed else None,
        reducer_wall_clock_seconds=0.1 if passed else None,
        complete_wall_clock_seconds=0.2,
        independent_verifications=(),
        final_verification_passed=passed,
        source_unchanged=source_unchanged,
    )


class _SequenceRunner:
    """Return predetermined results for isolated driver-verification tests."""

    def __init__(self, results: tuple[ExecutionResult, ...]) -> None:
        self._results = list(results)

    def run(self, working_directory: Path) -> ExecutionResult:
        """Return the next command result without executing a subprocess."""
        return self._results.pop(0)


def _failure_result(root: Path, exception_type: str, message: str) -> ExecutionResult:
    """Build a parseable uncaught-exception result within ``root``."""
    return ExecutionResult(
        command=("python", "run.py"),
        return_code=1,
        stdout="",
        stderr=(
            "Traceback (most recent call last):\n"
            f'  File "{root / "target.py"}", line 1, in fail\n'
            f"{exception_type}: {message}\n"
        ),
        timed_out=False,
    )


def _driver_module():
    """Load the standalone benchmark driver for unit-level failure tests."""
    spec = importlib.util.spec_from_file_location("benchmark_driver", DRIVER)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load benchmark driver")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixture(root: Path) -> None:
    _write(root, "pkg/__init__.py", "from .needed import Needed\n")
    _write(root, "pkg/needed.py", "class Needed:\n    pass\n")
    _write(root, "ballast.py", "class Unneeded:\n    pass\n")
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
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _write(root: Path, relative_path: str, content: str) -> None:
    """Write one fixture file beneath the temporary source project."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
