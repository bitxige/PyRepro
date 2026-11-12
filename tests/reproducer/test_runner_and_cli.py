"""Tests for bounded argv execution and the P1 module command-line interface."""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from pyrepro.reproducer import probe_report
from pyrepro.reproducer.__main__ import (
    _FAST_DEFAULT_STAGE_LIMITS,
    _fast_pipeline_limits,
    _standard_pipeline_limits,
    main,
)
from pyrepro.reproducer.publisher import FastModeTerminalState, PublishingResult
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult, _decode_output
from pyrepro.reproducer.workspace import tree_digest

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"
TRAINING_PROJECT = Path(__file__).parents[2] / "examples" / "training_failure"
SYMBOL_PROJECT = Path(__file__).parents[2] / "examples" / "symbol_failure"

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="atomic no-clobber publication requires Linux renameat2",
)


@pytest.fixture
def linux_platform(monkeypatch):
    """Pretend to run on Linux for tests that mock the publisher."""
    monkeypatch.setattr(sys, "platform", "linux")


def _disable_fast_source_stages() -> list[str]:
    """Return CLI options that isolate one Fast source-stage test."""
    return [
        "--max-symbol-probes",
        "0",
        "--max-method-probes",
        "0",
        "--max-if-statement-probes",
        "0",
        "--max-container-entry-probes",
        "0",
        "--max-list-entry-probes",
        "0",
        "--max-main-guard-probes",
        "0",
        "--max-nested-list-entry-probes",
        "0",
    ]


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


def test_runner_decodes_utf8_output_on_a_non_utf8_locale(tmp_path: Path):
    """UTF-8 child output must not abort reduction on a non-UTF-8 locale."""
    child = tmp_path / "child.py"
    child.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('中文标准输出\\n'.encode('utf-8'))\n"
        "sys.stdout.buffer.flush()\n"
        "raise ValueError('中文错误')\n",
        encoding="utf-8",
    )
    runner = CommandRunner((sys.executable, "child.py"), timeout_seconds=2)

    result = runner.run(tmp_path)

    assert result.stdout == "中文标准输出\n"
    assert "ValueError" in result.stderr


def test_decode_output_decodes_utf8_text():
    """UTF-8 output decodes even when the locale uses a legacy encoding."""
    assert _decode_output("中文".encode(), preferred_encoding="gbk") == "中文"


def test_decode_output_decodes_locale_encoded_text():
    """Locale-encoded output decodes after the UTF-8 attempt fails."""
    assert _decode_output("中文".encode("gbk"), preferred_encoding="gbk") == "中文"


def test_decode_output_prefers_utf8_when_both_encodings_decode():
    """UTF-8 wins when a byte sequence is valid in both encodings."""
    assert _decode_output("é".encode(), preferred_encoding="cp1252") == "é"


def test_decode_output_replaces_undecodable_bytes():
    """Invalid bytes become replacement characters instead of aborting."""
    decoded = _decode_output(b"\xff\xfe", preferred_encoding="utf-8")

    assert "\ufffd" in decoded


def test_decode_output_normalizes_windows_newlines():
    """Captured output keeps subprocess text mode's universal newlines."""
    assert _decode_output(b"a\r\nb\rc", preferred_encoding="utf-8") == "a\nb\nc"


def test_runner_does_not_wait_for_stdin(tmp_path: Path):
    """A command that reads stdin sees EOF instead of blocking reduction."""
    runner = CommandRunner(
        (sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"),
        timeout_seconds=2,
    )

    result = runner.run(tmp_path)

    assert not result.timed_out
    assert result.stdout.strip() == "0"


def test_runner_terminates_descendant_processes_on_timeout(tmp_path: Path):
    """A timed-out command must not leave background children running."""
    marker = tmp_path / "grandchild-marker.txt"
    grandchild = tmp_path / "grandchild.py"
    grandchild.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "time.sleep(1.0)\n"
        "Path(sys.argv[1]).write_text('alive', encoding='utf-8')\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.py"
    child.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[2], sys.argv[1]])\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    runner = CommandRunner(
        (sys.executable, "child.py", str(marker), str(grandchild)),
        timeout_seconds=0.5,
    )

    result = runner.run(tmp_path)

    assert result.timed_out
    time.sleep(1.5)
    assert not marker.exists()


def test_runner_caps_retained_output_at_the_tail(tmp_path: Path):
    """Large output keeps the traceback-relevant tail and reports truncation."""
    runner = CommandRunner(
        (sys.executable, "-c", "for _ in range(100): print('x' * 100)"),
        timeout_seconds=5,
        max_output_bytes=200,
    )

    result = runner.run(tmp_path)

    assert not result.timed_out
    assert result.stdout_truncated
    assert "[pyrepro] output truncated" in result.stdout
    assert result.stdout.rstrip().endswith("x" * 100)
    assert len(result.stdout.encode()) <= 200 + len(
        "\n[pyrepro] output truncated; showing the tail\n"
    )


def test_runner_rejects_non_positive_output_limit():
    """The retained tail must be a positive byte count."""
    with pytest.raises(ValueError, match="max_output_bytes"):
        CommandRunner(
            (sys.executable, "-c", "pass"), timeout_seconds=2, max_output_bytes=0
        )


def test_runner_notifies_execution_observer_before_each_command(tmp_path: Path):
    """Progress presentation can observe starts without changing command results."""
    started: list[str] = []
    runner = CommandRunner(
        (sys.executable, "-c", "raise KeyError('width')"),
        timeout_seconds=2,
        on_execution_start=lambda: started.append("started"),
    )

    result = runner.run(tmp_path)

    assert result.return_code != 0
    assert started == ["started"]


def test_reduce_help_documents_progress_control(capsys):
    """The progress display remains discoverable and explicitly controllable."""
    with pytest.raises(SystemExit) as error:
        main(["reduce", "--help"])

    captured = capsys.readouterr()

    assert error.value.code == 0
    assert "--progress {auto,on,off}" in captured.out
    assert "terminal reduction progress" in captured.out


def test_fast_default_stage_limits_match_the_rich_budget_b_configuration():
    """Keep Fast's production defaults aligned with the approved B allocation."""
    assert vars(_FAST_DEFAULT_STAGE_LIMITS) == {
        "import_pruning": 16,
        "coarse": 16,
        "symbol": 60,
        "method": 265,
        "if_statement": 60,
        "container_entry": 60,
        "list_entry": 60,
        "main_guard": 8,
        "nested_list_entry": 12,
    }


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
        "oracle_executions": 1,
        "passed": True,
        "required_runs": 1,
        "same_failure_runs": 1,
    }
    assert report["oracle"]["total_executions"] == (
        report["oracle"]["reduction_executions"]
        + report["oracle"]["final_verification_executions"]
    )
    assert report["size"]["loc_reduction_ratio"] == pytest.approx(
        report["size"]["loc_removed"] / report["size"]["input"]["python_loc"]
    )
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


@pytest.mark.parametrize(
    "mode_args",
    [
        ["--pytest-node", "tests/test_target.py::test_failure"],
        [
            "--mode",
            "fast",
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "6",
        ],
    ],
    ids=["standard", "fast"],
)
def test_reduce_rejects_target_aware_publication_off_linux(
    tmp_path: Path, monkeypatch, capsys, mode_args
):
    """Reject Linux-only publication before any reproduction command starts."""
    source = tmp_path / "source"
    source.mkdir()
    child = tmp_path / "child.py"
    child.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('executed').write_text('ran')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(SystemExit) as error:
        main(
            [
                "reduce",
                str(source),
                *mode_args,
                "--output",
                str(tmp_path / "output"),
                "--",
                sys.executable,
                str(child),
            ]
        )

    captured = capsys.readouterr()

    assert error.value.code == 2
    assert "Linux" in captured.err
    assert not (tmp_path / "executed").exists()


def test_legacy_standard_remains_available_off_linux(tmp_path: Path, monkeypatch):
    """The file-only CLI path does not require Linux publication."""
    monkeypatch.setattr(sys, "platform", "win32")
    output = tmp_path / "legacy-output"

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

    assert status == 0
    assert (output / "reproduce.py").is_file()


@linux_only
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


@linux_only
def test_standard_mode_cli_uses_the_shared_pipeline_and_publisher(
    tmp_path: Path, capsys
):
    """A target-aware Standard run is unbounded but retains final 3/3 staging."""
    source = tmp_path / "source"
    output = tmp_path / "standard-output"
    report_path = tmp_path / "standard.json"
    _fast_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--output",
            str(output),
            "--json-report",
            str(report_path),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert status == 0
    assert (
        "Pipeline: unbounded search with the Fast Mode reducer lineup." in captured.out
    )
    assert "Final verification: 3/3 passed" in captured.out
    assert report["mode"] == "standard"
    assert report["schema_version"] == 2
    assert report["oracle"]["budget"] is None
    assert report["pipeline"]["fixed_point_reached"]
    assert report["pipeline"]["termination_reason"] == "fixed_point"
    assert report["pipeline"]["sweep_count"] == len(report["sweeps"])
    assert report["sweeps"][-1]["accepted_edits"] == 0
    assert report["final_verification"]["completed_runs"] == 3
    assert report["final_verification"]["same_failure_runs"] == 3
    assert report["oracle"]["baseline_executions"] == 3
    assert report["oracle"]["search_executions"] == (
        report["oracle"]["reduction_executions"] - 3
    )
    assert (output / "run_target.py").is_file()


@linux_only
def test_standard_mode_honors_an_explicit_global_execution_limit(
    tmp_path: Path,
    capsys,
):
    """A Standard cap reserves final 3/3 rather than changing mode semantics."""
    source = tmp_path / "source"
    output = tmp_path / "standard-output"
    _fast_project(source)

    status = main(
        [
            "reduce",
            str(source),
            "--pytest-node",
            "tests/test_target.py::test_failure",
            "--max-oracle-executions",
            "6",
            "--output",
            str(output),
            "--",
            sys.executable,
            "run_target.py",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "explicit search limit" in captured.out
    assert (output / "run_target.py").is_file()


@linux_only
def test_fast_mode_cli_optionally_writes_final_result_reports(tmp_path: Path, capsys):
    """Final JSON and HTML reports describe the verified publication result."""
    source = tmp_path / "source"
    output = tmp_path / "output"
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
    assert report["schema_version"] == 2
    assert report["mode"] == "fast"
    assert report["pipeline"]["termination_reason"] == "budget_exhausted"
    assert report["pipeline"]["sweep_count"] == len(report["sweeps"])
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
    assert report["oracle"]["baseline_executions"] == 3
    assert report["oracle"]["search_executions"] == (
        report["oracle"]["reduction_executions"] - 3
    )
    assert report["oracle"]["total_executions"] == (
        report["oracle"]["reduction_executions"]
        + report["oracle"]["final_verification_executions"]
    )
    assert (
        report["final_verification"]["oracle_executions"]
        == report["oracle"]["final_verification_executions"]
    )
    assert report["size"]["input"]["python_loc"] > 0
    assert report["size"]["published_output"] == report["size"]["candidate"]
    assert "JSON report:" in captured.out
    assert "HTML report:" in captured.out
    assert "PyRepro reduction report" in html_report.read_text(encoding="utf-8")


def test_standard_fast_config_policy_matches_fast_stage_enablement():
    """A controlled comparison can share one enabled-stage set."""
    args = type(
        "Arguments",
        (),
        {
            "max_import_probes": 16,
            "max_coarse_probes": 0,
            "max_symbol_probes": 60,
            "max_method_probes": 0,
            "max_if_statement_probes": 8,
            "max_container_entry_probes": 0,
            "max_list_entry_probes": 0,
            "max_main_guard_probes": 4,
            "max_nested_list_entry_probes": 0,
            "standard_stage_policy": "fast-config",
        },
    )()

    fast = _fast_pipeline_limits(args)
    standard = _standard_pipeline_limits(args)
    for name, fast_limit in vars(fast).items():
        assert (fast_limit > 0) is (getattr(standard, name) is None)


@linux_only
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


@linux_only
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
            *_disable_fast_source_stages(),
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


@linux_only
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
            *_disable_fast_source_stages(),
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


@linux_only
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
            *_disable_fast_source_stages(),
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


@linux_only
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
            *_disable_fast_source_stages(),
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


@linux_only
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
            *_disable_fast_source_stages(),
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


@linux_only
def test_fast_mode_cli_runs_list_entry_reduction_by_default(tmp_path: Path, capsys):
    """Fast's B configuration makes list-entry reduction available by default."""
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
    assert "List-entry probes:" in captured.out
    assert "List entries removed: 1" in captured.out
    assert "(3, 4, 0)" not in (output / "target.py").read_text(encoding="utf-8")
    assert tree_digest(source) == source_digest


@linux_only
def test_fast_mode_cli_optionally_runs_main_guard_probes(tmp_path: Path, capsys):
    """Main-guard probes retain Fast publisher verification and telemetry."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_main_guard_project(source)

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
            *_disable_fast_source_stages(),
            "--max-main-guard-probes",
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
    assert "Main-guard probes: 1 (1 accepted)" in captured.out
    assert "Main guards removed: 2" in captured.out
    assert "if __name__" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["phase"] == "main_guard" for record in records)


@linux_only
def test_fast_mode_cli_runs_main_guard_reduction_by_default(tmp_path: Path, capsys):
    """Fast's B configuration makes main-guard reduction available by default."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    _fast_main_guard_project(source)
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
    assert "Main-guard probes: 1 (1 accepted)" in captured.out
    assert "Main guards removed: 2" in captured.out
    assert "if __name__" not in (output / "target.py").read_text(encoding="utf-8")
    assert tree_digest(source) == source_digest


@linux_only
def test_fast_mode_cli_optionally_runs_nested_list_entry_probes(tmp_path: Path, capsys):
    """Nested list-entry probes retain publisher verification and telemetry."""
    source = tmp_path / "source"
    output = tmp_path / "verified-output"
    report = tmp_path / "probes.jsonl"
    _fast_nested_palette_project(source)

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
            *_disable_fast_source_stages(),
            "--max-nested-list-entry-probes",
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
    assert "Nested-list-entry probes: 1 (1 accepted)" in captured.out
    assert "Nested list entries removed: 2" in captured.out
    assert "(1, 2, 3)" not in (output / "target.py").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["phase"] == "nested_list_entry" for record in records)


def test_fast_mode_cli_rejects_negative_nested_list_entry_probe_limit(
    tmp_path: Path, capsys
):
    """The nested-list entry stage follows the Fast-Mode bound contract."""
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
                "--max-nested-list-entry-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-nested-list-entry-probes must not be negative" in captured.err


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


def test_fast_mode_cli_rejects_negative_main_guard_probe_limit(tmp_path: Path, capsys):
    """The optional main-guard stage follows the Fast-Mode bound contract."""
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
                "--max-main-guard-probes",
                "-1",
                "--",
                sys.executable,
                "-c",
                "raise ValueError('failure')",
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "--max-main-guard-probes must not be negative" in captured.err


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
                "--max-symbol-probes",
                "0",
                "--max-method-probes",
                "0",
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
    tmp_path: Path, capsys, linux_platform
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
    linux_platform,
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


def _fast_main_guard_project(root: Path) -> None:
    """Create a retained failure with two removable direct main guards."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "if __name__ == '__main__':  # pragma: no cover\n"
        "    print('unused')\n\n"
        "if '__main__' == __name__:\n"
        "    print('also unused')\n\n"
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


def _fast_nested_palette_project(root: Path) -> None:
    """Create one preserved nested Palette list with removable RGB entries."""
    _write(root, "tests/__init__.py", "")
    _write(
        root,
        "target.py",
        "class Palette:\n"
        "    def __init__(self, colors, *, label):\n"
        "        self.colors = colors\n\n"
        "CUSTOM_COLORS = Palette(\n"
        "    [\n        (1, 2, 3),\n        (4, 5, 6),\n    ],\n"
        "    label='test',\n"
        ")\n\n"
        "def target_failure() -> None:\n"
        "    assert isinstance(CUSTOM_COLORS.colors, list)\n"
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
