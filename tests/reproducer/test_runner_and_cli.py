"""Tests for bounded argv execution and the P1 module command-line interface."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer import probe_report
from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.publisher import FastModeTerminalState, PublishingResult
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult
from pyrepro.reproducer.workspace import tree_digest

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"
TRAINING_PROJECT = Path(__file__).parents[2] / "examples" / "training_failure"
SYMBOL_PROJECT = Path(__file__).parents[2] / "examples" / "symbol_failure"


def test_runner_captures_uncaught_exception_output(tmp_path: Path):
    """Capture stderr and nonzero exit status without invoking a shell."""
    runner = CommandRunner(
        (sys.executable, "-c", "raise KeyError('width')"), timeout_seconds=2
    )

    result = runner.run(tmp_path)

    assert result.return_code != 0
    assert not result.timed_out
    assert "KeyError: 'width'" in result.stderr


def test_runner_reports_timeout(tmp_path: Path):
    """Return a timeout result instead of propagating TimeoutExpired."""
    runner = CommandRunner(
        (sys.executable, "-c", "import time; time.sleep(1)"), timeout_seconds=0.01
    )

    result = runner.run(tmp_path)

    assert result.timed_out
    assert result.return_code is None


def test_module_cli_writes_a_verified_reduced_project(tmp_path: Path, capsys):
    """Run the P1 loop through the public subcommand entry point."""
    output = tmp_path / "reduced-project"

    status = main(
        [
            "reduce",
            str(FAILING_PROJECT),
            "--output",
            str(output),
            "--",
            sys.executable,
            "reproduce.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Stable: 3/3" in captured.out
    assert "Original modified: no" in captured.out
    assert "Probe telemetry" in captured.out
    assert "Different failures:" in captured.out
    assert (output / "reproduce.py").is_file()


def test_standard_mode_cli_optionally_writes_final_result_reports(
    tmp_path: Path, capsys
):
    """Standard Mode reports its one-run copied-output verification accurately."""
    output = tmp_path / "reduced-project"
    json_report = tmp_path / "result.json"
    html_report = tmp_path / "result.html"

    status = main(
        [
            "reduce",
            str(FAILING_PROJECT),
            "--output",
            str(output),
            "--json-report",
            str(json_report),
            "--html-report",
            str(html_report),
            "--",
            sys.executable,
            "reproduce.py",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(json_report.read_text(encoding="utf-8"))

    assert status == 0
    assert report["mode"] == "standard"
    assert report["status"]["verified"]
    assert report["final_verification"] == {
        "attempts": [],
        "completed_runs": 1,
        "passed": True,
        "required_runs": 1,
        "same_failure_runs": 1,
    }
    assert "JSON report:" in captured.out
    assert "HTML report:" in captured.out
    assert "PyRepro reduction report" in html_report.read_text(encoding="utf-8")


def test_standard_mode_rejects_an_output_copy_with_a_different_failure(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
):
    """Do not report success when copied output no longer matches the baseline."""
    output = tmp_path / "reduced-project"
    original_run = CommandRunner.run

    def return_success_for_copied_output(
        runner: CommandRunner,
        working_directory: Path,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        if working_directory == output:
            return ExecutionResult(
                command=runner.command,
                return_code=0,
                stdout="",
                stderr="",
                timed_out=False,
            )
        return original_run(
            runner,
            working_directory,
            timeout_seconds=timeout_seconds,
        )

    monkeypatch.setattr(CommandRunner, "run", return_success_for_copied_output)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(output),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    captured = capsys.readouterr()

    assert error.value.code == 2
    assert (
        "copied reduced project did not reproduce the baseline failure" in captured.err
    )
    assert "Reduced project:" not in captured.out
    assert (output / "reproduce.py").is_file()


def test_module_cli_optionally_writes_jsonl_probe_records(tmp_path: Path, capsys):
    """Exported telemetry must describe probes without changing reduction output."""
    without_report = tmp_path / "without-report"
    with_report = tmp_path / "with-report"
    report = tmp_path / "probes.jsonl"

    assert (
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(without_report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(with_report),
                "--probe-records",
                str(report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    records = [json.loads(line) for line in report.read_text().splitlines()]
    assert tree_digest(with_report) == tree_digest(without_report)
    assert "Probe records:" in captured.out
    assert len(records) == 12
    assert {
        "accepted",
        "candidate",
        "duration_seconds",
        "elapsed_seconds",
        "failure_message",
        "failure_signature",
        "failure_type",
        "outcome",
        "phase",
        "probe_id",
        "remaining_python_loc",
        "return_code",
    } <= records[0].keys()
    assert [record["probe_id"] for record in records] == list(
        range(1, len(records) + 1)
    )
    assert {record["phase"] for record in records} == {"greedy"}
    assert all(record["candidate"] for record in records)
    assert any(record["accepted"] for record in records)
    assert all(isinstance(record["remaining_python_loc"], int) for record in records)
    assert [record["elapsed_seconds"] for record in records] == sorted(
        record["elapsed_seconds"] for record in records
    )


def test_module_cli_rejects_probe_records_inside_source_project(tmp_path: Path, capsys):
    """Keep the optional telemetry artifact out of the protected source tree."""
    report = FAILING_PROJECT / "probes.jsonl"

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(tmp_path / "output"),
                "--probe-records",
                str(report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "probe report path must be outside the source root" in captured.err
    assert not report.exists()


def test_module_cli_rejects_an_existing_probe_report(tmp_path: Path, capsys):
    """Do not overwrite a pre-existing telemetry artifact."""
    report = tmp_path / "probes.jsonl"
    report.write_text("previous telemetry\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(tmp_path / "output"),
                "--probe-records",
                str(report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "probe report path already exists" in captured.err
    assert report.read_text(encoding="utf-8") == "previous telemetry\n"


def test_module_cli_rejects_probe_and_final_report_path_overlap(tmp_path: Path, capsys):
    """Probe telemetry and the final summary cannot overwrite one another."""
    report = tmp_path / "report.json"

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(tmp_path / "output"),
                "--probe-records",
                str(report),
                "--json-report",
                str(report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    captured = capsys.readouterr()

    assert error.value.code == 2
    assert "probe report and final report paths must be different" in captured.err
    assert not report.exists()


def test_module_cli_cleans_failed_probe_report_and_preserves_output(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
):
    """Report publication failures must not corrupt output or leak temp files."""
    output = tmp_path / "output"
    report = tmp_path / "probes.jsonl"

    def fail_link(source: Path, target: Path) -> None:
        del source, target
        raise OSError("simulated publication failure")

    monkeypatch.setattr(probe_report.os, "link", fail_link)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(FAILING_PROJECT),
                "--output",
                str(output),
                "--probe-records",
                str(report),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "failed to write probe records" in captured.err
    assert str(output) in captured.err
    assert "Traceback" not in captured.err
    assert (output / "reproduce.py").is_file()
    assert not report.exists()
    assert not list(tmp_path.glob(".probes.jsonl.*.tmp"))


def test_module_cli_reduces_a_trusted_local_training_project(tmp_path: Path, capsys):
    """Allow a non-P0 local project while preserving an expected failure."""
    output = tmp_path / "reduced-training-project"

    status = main(
        [
            "reduce",
            str(TRAINING_PROJECT),
            "--output",
            str(output),
            "--expect",
            "operands could not be broadcast",
            "--",
            sys.executable,
            "train.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Warning: PyRepro will repeatedly execute" in captured.out
    assert "ValueError: operands could not be broadcast" in captured.out
    assert (output / "reward" / "shaping.py").is_file()


def test_module_cli_supports_message_matching_for_comparison(tmp_path: Path):
    """Expose message-only matching without changing the strict default."""
    output = tmp_path / "message-output"

    status = main(
        [
            "reduce",
            str(TRAINING_PROJECT),
            "--output",
            str(output),
            "--failure-match",
            "message",
            "--",
            sys.executable,
            "train.py",
        ]
    )

    assert status == 0
    assert (output / "reward" / "shaping.py").is_file()


def test_module_cli_uses_a_sibling_default_output_directory(tmp_path: Path):
    """Keep the default output outside the trusted source project."""
    source = tmp_path / "training-project"
    shutil.copytree(TRAINING_PROJECT, source)

    status = main(
        [
            "reduce",
            str(source),
            "--",
            sys.executable,
            "train.py",
        ]
    )

    assert status == 0
    assert (tmp_path / ".pyrepro-output" / source.name / "train.py").is_file()


def test_module_cli_rejects_a_nonmatching_expected_failure(tmp_path: Path):
    """Abort before deletion when --expect does not match the baseline."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(TRAINING_PROJECT),
                "--output",
                str(tmp_path / "output"),
                "--expect",
                "IndexError",
                "--",
                sys.executable,
                "train.py",
            ]
        )

    assert error.value.code == 2


def test_module_cli_rejects_a_blank_expected_failure(tmp_path: Path):
    """Present an argparse error instead of leaking a constructor ValueError."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(TRAINING_PROJECT),
                "--output",
                str(tmp_path / "output"),
                "--expect",
                "   ",
                "--",
                sys.executable,
                "train.py",
            ]
        )

    assert error.value.code == 2


def test_module_cli_runs_the_ddmin_strategy(tmp_path: Path, capsys):
    """Expose the P2 grouped reducer through the public CLI strategy option."""
    output = tmp_path / "ddmin-output"
    report = tmp_path / "ddmin-probes.jsonl"

    status = main(
        [
            "reduce",
            str(FAILING_PROJECT),
            "--output",
            str(output),
            "--probe-records",
            str(report),
            "--strategy",
            "ddmin",
            "--",
            sys.executable,
            "reproduce.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Strategy: ddmin" in captured.out
    assert "Oracle executions:" in captured.out
    assert (output / "reproduce.py").is_file()
    records = [json.loads(line) for line in report.read_text().splitlines()]
    assert records
    assert {record["phase"] for record in records} <= {
        "subset",
        "complement",
        "cleanup",
        "minimality",
    }
    assert all(isinstance(record["remaining_python_loc"], int) for record in records)


@pytest.mark.parametrize("strategy", ("greedy", "ddmin"))
def test_module_cli_runs_symbol_reduction_after_the_file_strategy(
    tmp_path: Path, capsys, strategy: str
):
    """Run P3 after either supported file-reduction strategy."""
    output = tmp_path / f"symbol-output-{strategy}"

    status = main(
        [
            "reduce",
            str(SYMBOL_PROJECT),
            "--output",
            str(output),
            "--max-granularity",
            "symbol",
            "--strategy",
            strategy,
            "--",
            sys.executable,
            "reproduce.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert f"Strategy: {strategy}" in captured.out
    assert "Symbol reduction" in captured.out
    assert "Supported symbols:" in captured.out
    assert "Total oracle executions:" in captured.out
    assert "RewardComparisonArchive" not in (
        output / "reward" / "shaping.py"
    ).read_text(encoding="utf-8")


def test_fast_mode_cli_publishes_a_verified_reproducer(tmp_path: Path, capsys):
    """Wire target-aware reduction, final verification, and publication together."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    _fast_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "7",
            "--max-coarse-probes",
            "0",
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "accepted candidate passed final 3/3 verification" in captured.out
    assert f"Published reproducer: {output}" in captured.out
    assert "Final verification: 3/3 passed" in captured.out
    assert (output / "run_target.py").is_file()
    assert "from ballast import Unneeded" not in (
        output / "tests/test_target.py"
    ).read_text(encoding="utf-8")


def test_fast_mode_cli_optionally_writes_final_result_reports(tmp_path: Path, capsys):
    """Final JSON and HTML reports describe the verified publication result."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    json_report = tmp_path / "result.json"
    html_report = tmp_path / "result.html"
    _fast_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "7",
            "--max-coarse-probes",
            "0",
            "--json-report",
            str(json_report),
            "--html-report",
            str(html_report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(json_report.read_text(encoding="utf-8"))

    assert status == 0
    assert report["schema_version"] == 1
    assert report["mode"] == "fast"
    assert report["status"] == {
        "error_message": None,
        "output_path": str(output.resolve()),
        "published": True,
        "search_budget_exhausted": True,
        "source_unchanged": True,
        "terminal_state": "budget_exhausted_verified",
        "verified": True,
    }
    assert report["final_verification"]["same_failure_runs"] == 3
    assert report["final_verification"]["required_runs"] == 3
    assert report["size"]["input"]["python_loc"] > 0
    assert report["size"]["published_output"] is not None
    assert "JSON report:" in captured.out
    assert "HTML report:" in captured.out
    assert "PyRepro reduction report" in html_report.read_text(encoding="utf-8")


def test_fast_mode_cli_minimum_budget_reserves_final_verification(
    tmp_path: Path, capsys
):
    """Six commands safely publish a verified candidate without search probes."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    _fast_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "6",
            "--max-coarse-probes",
            "0",
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Search probes: 0" in captured.out
    assert "accepted candidate passed final 3/3 verification" in captured.out
    assert (output / "run_target.py").is_file()
    assert "from ballast import Unneeded" in (
        output / "tests/test_target.py"
    ).read_text(encoding="utf-8")


def test_fast_mode_cli_optionally_runs_span_ordered_symbol_probes(
    tmp_path: Path, capsys
):
    """Fast Mode keeps Publisher verification while adding opt-in symbols."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_symbol_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--max-symbol-probes",
            "1",
            "--symbol-order",
            "span-desc",
            "--probe-records",
            str(report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "Symbol probes: 1 (1 accepted)" in captured.out
    assert "Method probes:" not in captured.out
    assert "If-statement probes:" not in captured.out
    assert "removable_ballast" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["phase"] == "symbol" for record in records)


def test_fast_mode_cli_optionally_runs_span_ordered_method_probes(
    tmp_path: Path, capsys
):
    """Method probes are opt-in and retain Fast publisher verification."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_method_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--max-method-probes",
            "1",
            "--symbol-order",
            "span-desc",
            "--probe-records",
            str(report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "Method probes: 1 (1 accepted)" in captured.out
    assert "def removable_ballast" not in (output / "target.py").read_text(
        encoding="utf-8"
    )
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    method_record = next(record for record in records if record["phase"] == "symbol")
    assert method_record["candidate_details"] == [
        "target.py:FailureService.removable_ballast:2-3:method"
    ]
    assert not method_record["candidate_rolled_back"]


def test_fast_mode_cli_optionally_runs_complete_if_probes(tmp_path: Path, capsys):
    """Experimental complete-if probes retain Fast publisher verification."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_if_statement_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--max-if-statement-probes",
            "2",
            "--probe-records",
            str(report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "If-statement probes: 2 (1 accepted)" in captured.out
    assert "ballast = 2" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    if_record = next(record for record in records if record["phase"] == "if_statement")
    assert if_record["candidate_rolled_back"]


def test_fast_mode_cli_optionally_runs_container_entry_probes(tmp_path: Path, capsys):
    """Container-entry probes retain Fast publisher verification and telemetry."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_container_entry_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--max-container-entry-probes",
            "4",
            "--probe-records",
            str(report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "Container-entry probes:" in captured.out
    assert "Container entries removed: 1" in captured.out
    assert "'unused'" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["phase"] == "container_entry" for record in records)


def test_fast_mode_cli_optionally_runs_list_entry_probes(tmp_path: Path, capsys):
    """List-entry probes share Fast publisher verification and telemetry."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_list_entry_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--max-list-entry-probes",
            "4",
            "--probe-records",
            str(report),
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "List-entry probes:" in captured.out
    assert "List entries removed: 1" in captured.out
    assert "(3, 4, 0)" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["phase"] == "list_entry" for record in records)


def test_fast_mode_cli_leaves_list_entry_reduction_disabled_by_default(
    tmp_path: Path, capsys
):
    """Do not run list-entry probes unless their explicit budget is positive."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    _fast_list_entry_project(source)
    source_digest = tree_digest(source)

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "20",
            "--max-coarse-probes",
            "0",
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 0
    assert "Final verification: 3/3 passed" in captured.out
    assert "List-entry probes:" not in captured.out
    assert "(3, 4, 0)" in (output / "target.py").read_text(encoding="utf-8")
    assert tree_digest(source) == source_digest


def test_fast_mode_cli_rejects_negative_container_entry_probe_limit(
    tmp_path: Path, capsys
):
    """The optional container-entry stage follows Fast validation rules."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--pytest-node",
                "tests/test_target.py::test_failure",
                "--max-oracle-executions",
                "6",
                "--max-container-entry-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-container-entry-probes must not be negative" in captured.err


def test_fast_mode_cli_rejects_negative_list_entry_probe_limit(tmp_path: Path, capsys):
    """The optional list-entry stage follows the Fast-Mode bound contract."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--pytest-node",
                "tests/test_target.py::test_failure",
                "--max-oracle-executions",
                "6",
                "--max-list-entry-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-list-entry-probes must not be negative" in captured.err


def test_fast_mode_cli_rejects_negative_complete_if_probe_limit(tmp_path: Path, capsys):
    """The experimental complete-if bound follows Fast validation rules."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--pytest-node",
                "tests/test_target.py::test_failure",
                "--max-oracle-executions",
                "6",
                "--max-if-statement-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-if-statement-probes must not be negative" in captured.err


def test_fast_mode_cli_rejects_an_unused_symbol_order(tmp_path: Path, capsys):
    """Do not silently accept a requested order while the stage is disabled."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--pytest-node",
                "tests/test_target.py::test_failure",
                "--max-oracle-executions",
                "6",
                "--symbol-order",
                "span-desc",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--symbol-order requires --max-symbol-probes or --max-method-probes" in (
        captured.err
    )


def test_fast_mode_cli_rejects_negative_method_probe_limit(tmp_path: Path, capsys):
    """Method probe bounds follow the same Fast-Mode validation contract."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--pytest-node",
                "tests/test_target.py::test_failure",
                "--max-oracle-executions",
                "6",
                "--max-method-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-method-probes must not be negative" in captured.err


def test_fast_mode_cli_leaves_existing_output_to_verified_publisher(
    tmp_path: Path, capsys
):
    """The CLI reports publisher rejection without duplicating no-clobber checks."""
    source = tmp_path / "source"
    output = tmp_path / "existing-output"
    _fast_project(source)
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "6",
            "--max-coarse-probes",
            "0",
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 1
    assert "Fast Mode failed: runtime_error" in captured.err
    assert "output directory already exists" in captured.err
    assert "No official reproducer was published." in captured.err
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            FastModeTerminalState.BUDGET_EXHAUSTED_UNVERIFIED,
            "the budget ended before final 3/3 verification completed",
        ),
        (
            FastModeTerminalState.FINAL_VERIFICATION_FAILED,
            "final verification did not reproduce the baseline failure",
        ),
        (FastModeTerminalState.SOURCE_CHANGED, "the protected source changed"),
    ],
)
def test_fast_mode_cli_maps_unpublished_terminal_states(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    state: FastModeTerminalState,
    message: str,
):
    """Map existing unpublished publisher states through the public CLI."""
    source = tmp_path / "source"
    output = tmp_path / "unpublished-output"
    json_report = tmp_path / "result.json"
    _fast_project(source)

    def unpublished_result(*args, **kwargs):
        budget = args[5]
        return PublishingResult(
            state=state,
            output_path=None,
            verification_attempts=(),
            source_unchanged=state is not FastModeTerminalState.SOURCE_CHANGED,
            budget=budget.snapshot(),
        )

    monkeypatch.setattr(
        "pyrepro.reproducer.__main__.verify_and_publish", unpublished_result
    )

    status = main(
        [
            "reduce",
            str(source),
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "6",
            "--max-coarse-probes",
            "0",
            "--output",
            str(output),
            "--json-report",
            str(json_report),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()

    assert status == 1
    assert f"Fast Mode failed: {message}" in captured.out
    assert "No official reproducer was published." in captured.out
    assert "Published reproducer:" not in captured.out
    assert not output.exists()
    report = json.loads(json_report.read_text(encoding="utf-8"))
    assert report["status"]["terminal_state"] == state.value
    assert not report["status"]["verified"]
    assert not report["status"]["published"]
    assert report["size"]["published_output"] is None


def test_fast_mode_cli_requires_compatible_fast_arguments(tmp_path: Path):
    """Reject unsupported Fast-Mode combinations rather than ignoring them."""
    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(tmp_path),
                "--mode",
                "fast",
                "--max-oracle-executions",
                "6",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    assert error.value.code == 2


def _fast_project(root: Path) -> None:
    """Create one small target-aware project for Fast-Mode CLI coverage."""
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


def _fast_symbol_project(root: Path) -> None:
    """Create a retained module with a large removable top-level function."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "def removable_ballast() -> int:\n"
        "    first = 1\n"
        "    second = 2\n"
        "    third = 3\n"
        "    return first + second + third\n\n"
        "def target_failure() -> None:\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "tests/test_target.py",
        "from target import target_failure\n\n"
        "def test_failure() -> None:\n"
        "    target_failure()\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _fast_method_project(root: Path) -> None:
    """Create a retained class with a removable direct method."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "class FailureService:\n"
        "    def removable_ballast(self) -> int:\n"
        "        return 1\n\n"
        "    def target_failure(self) -> None:\n"
        "        raise ValueError('target failure')\n\n"
        "    def spare(self) -> None:\n"
        "        pass\n",
    )
    _write(
        root,
        "tests/test_target.py",
        "from target import FailureService\n\n"
        "def test_failure() -> None:\n"
        "    FailureService().target_failure()\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _fast_if_statement_project(root: Path) -> None:
    """Create a retained function with one required and one removable if."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "def target_failure() -> None:\n"
        "    if True:\n"
        "        required = 1\n"
        "    if True:\n"
        "        ballast = 2\n"
        "    assert required == 1\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "tests/test_target.py",
        "from target import target_failure\n\n"
        "def test_failure() -> None:\n"
        "    target_failure()\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _fast_container_entry_project(root: Path) -> None:
    """Create a retained failure with one required dictionary entry."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "CODES = {\n"
        "    'needed': 'present',\n"
        "    'unused': 'ballast',\n"
        "}\n\n"
        "def target_failure() -> None:\n"
        "    CODES['needed']\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "tests/test_target.py",
        "from target import target_failure\n\n"
        "def test_failure() -> None:\n"
        "    target_failure()\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _fast_list_entry_project(root: Path) -> None:
    """Create a retained failure with one required static list tuple."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "CELL_WIDTHS = [\n"
        "    (1, 2, -1),\n"
        "    (3, 4, 0),\n"
        "]\n\n"
        "def target_failure() -> None:\n"
        "    assert (1, 2, -1) in CELL_WIDTHS\n"
        "    raise ValueError('target failure')\n",
    )
    _write(
        root,
        "tests/test_target.py",
        "from target import target_failure\n\n"
        "def test_failure() -> None:\n"
        "    target_failure()\n",
    )
    _write(
        root,
        "run_target.py",
        "from tests.test_target import test_failure\ntest_failure()\n",
    )


def _write(root: Path, relative_path: str, content: str) -> None:
    """Write one UTF-8 fixture file under a project root."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
