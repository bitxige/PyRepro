"""Tests for bounded argv execution and the P0 module command-line interface."""

import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.runner import CommandRunner

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"


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
    """Run the complete P0 loop through the isolated module entry point."""
    output = tmp_path / "reduced-project"

    status = main(
        [
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


def test_module_cli_rejects_an_untrusted_source_root(tmp_path: Path):
    """Limit P0 execution to the repository-owned deterministic fixture."""
    untrusted_source = tmp_path / "untrusted"
    untrusted_source.mkdir()

    with pytest.raises(SystemExit) as error:
        main(
            [
                str(untrusted_source),
                "--output",
                str(tmp_path / "output"),
                "--",
                sys.executable,
                "reproduce.py",
            ]
        )

    assert error.value.code == 2
