"""Test comparison metrics and external-command placeholder handling."""

import sys
from pathlib import Path

from pyrepro.competitive_study.compare import (
    expand_command,
    measure_workspace,
    run_external,
    source_digest,
)


def test_expand_command_replaces_only_explicit_placeholders(tmp_path: Path) -> None:
    """Replace only exact path placeholders in an external command."""
    source = tmp_path / "source"
    output = tmp_path / "output"
    oracle = tmp_path / "oracle.py"

    command = expand_command(
        ["tool", "--input", "{source}", "--output", "{output}", "{oracle}"],
        source,
        output,
        oracle,
    )

    assert command == (
        "tool",
        "--input",
        str(source),
        "--output",
        str(output),
        str(oracle),
    )


def test_measure_workspace_counts_python_lines_and_top_level_symbols(
    tmp_path: Path,
) -> None:
    """Count files, physical Python lines, and module-level symbols."""
    (tmp_path / "main.py").write_text(
        "def run():\n    return 1\n\nclass Helper:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")

    stats = measure_workspace(tmp_path)

    assert stats.total_files == 2
    assert stats.python_files == 1
    assert stats.python_loc == 5
    assert stats.top_level_symbols == 2


def test_external_run_uses_disposable_source_and_three_run_verification(
    tmp_path: Path,
):
    """Protect the source and separate baseline from reduced verification runs."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "reproduce.py").write_text("raise KeyError('width')\n", encoding="utf-8")
    reducer = tmp_path / "copy_reducer.py"
    reducer.write_text(
        "import shutil, sys\nshutil.copytree(sys.argv[1], sys.argv[2])\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    result = run_external(
        "copy",
        [sys.executable, str(reducer), "{source}", "{output}"],
        source,
        output,
        tmp_path / "results",
        [sys.executable, "reproduce.py"],
        timeout_seconds=2,
    )

    assert result.baseline_runs == 3
    assert result.baseline_stable
    assert result.reduced_verification_runs == 3
    assert result.reduced_stable
    assert result.verification_executions == 6
    assert result.failure_preserved
    assert result.source_unchanged
    assert result.source_digest_before == result.source_digest_after
    assert source_digest(source) == result.source_digest_after
