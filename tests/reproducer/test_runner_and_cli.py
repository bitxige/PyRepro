"""Tests for bounded argv execution and the P1 module command-line interface."""

import shutil
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.runner import CommandRunner

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"
TRAINING_PROJECT = Path(__file__).parents[2] / "examples" / "training_failure"


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
    assert (output / "reproduce.py").is_file()


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
