"""Tests for bounded argv execution and the P1 module command-line interface."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer import probe_report
from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.runner import CommandRunner
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
