"""Test comparison metrics and external-command placeholder handling."""

from pathlib import Path

from pyrepro.competitive_study.compare import expand_command, measure_workspace


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
