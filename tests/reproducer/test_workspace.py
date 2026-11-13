"""Tests for disposable workspaces and source-integrity digests."""

from pathlib import Path

import pytest
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink or skip when the platform cannot create one."""
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


def test_tree_digest_changes_when_source_content_changes(tmp_path: Path):
    """A real source edit must change the protected digest."""
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    before = tree_digest(source)

    (source / "app.py").write_text("value = 2\n", encoding="utf-8")

    assert tree_digest(source) != before


def test_tree_digest_can_normalize_text_line_endings_for_fixture_manifests(
    tmp_path: Path,
):
    """Portable fixture digests treat CRLF and LF text as the same source."""
    source = tmp_path / "project"
    source.mkdir()
    app = source / "app.py"
    app.write_bytes(b"value = 1\r\n")
    raw_crlf = tree_digest(source)
    portable_crlf = tree_digest(source, normalize_text_line_endings=True)

    app.write_bytes(b"value = 1\n")

    assert tree_digest(source) != raw_crlf
    assert tree_digest(source, normalize_text_line_endings=True) == portable_crlf


def test_tree_digest_ignores_vcs_cache_and_environment_directories(tmp_path: Path):
    """Non-source directories cannot create false integrity failures."""
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    before = tree_digest(source)

    for name in (".git", "__pycache__", ".venv", "node_modules", "build"):
        directory = source / name
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored", encoding="utf-8")
    assert tree_digest(source) == before

    (source / ".git" / "ignored.txt").write_text("changed", encoding="utf-8")

    assert tree_digest(source) == before


def test_tree_digest_retains_data_directories(tmp_path: Path):
    """Data directories can affect reproduction and stay in the digest."""
    source = tmp_path / "project"
    source.mkdir()
    data = source / "data"
    data.mkdir()
    (data / "sample.txt").write_text("one", encoding="utf-8")
    before = tree_digest(source)

    (data / "sample.txt").write_text("two", encoding="utf-8")

    assert tree_digest(source) != before


def test_tree_digest_hashes_symlink_targets(tmp_path: Path):
    """Changing a link target changes the digest without reading its content."""
    source = tmp_path / "project"
    source.mkdir()
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    link = source / "link.txt"
    _symlink_or_skip(link, first)
    before = tree_digest(source)

    link.unlink()
    _symlink_or_skip(link, second)

    assert tree_digest(source) != before


def test_tree_digest_does_not_follow_symlink_content(tmp_path: Path):
    """An external link's content is not part of the source digest."""
    source = tmp_path / "project"
    source.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("one", encoding="utf-8")
    _symlink_or_skip(source / "link.txt", external)
    before = tree_digest(source)

    external.write_text("two", encoding="utf-8")

    assert tree_digest(source) == before


def test_workspace_detects_source_change_after_creation(tmp_path: Path):
    """The original source digest is compared after a workspace is created."""
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    workspace = ReductionWorkspace(source)

    (source / "app.py").write_text("value = 2\n", encoding="utf-8")

    assert not workspace.source_is_unchanged()


def test_workspace_copies_source_and_keeps_original_unchanged(tmp_path: Path):
    """Edits in the disposable copy do not affect the protected source."""
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")

    with ReductionWorkspace(source) as workspace:
        (workspace.root / "app.py").write_text("changed\n", encoding="utf-8")
        destination = workspace.copy_reduced_to(tmp_path / "output")

        assert (destination / "app.py").read_text(encoding="utf-8") == "changed\n"

    assert (source / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert workspace.source_is_unchanged()


def test_workspace_materializes_symlinks_in_the_copy(tmp_path: Path):
    """The disposable copy follows links so the command can run portably."""
    source = tmp_path / "project"
    source.mkdir()
    target = source / "target.txt"
    target.write_text("content", encoding="utf-8")
    _symlink_or_skip(source / "link.txt", target)

    with ReductionWorkspace(source) as workspace:
        copied = workspace.root / "link.txt"

        assert not copied.is_symlink()
        assert copied.read_text(encoding="utf-8") == "content"


def test_workspace_rejects_output_inside_source(tmp_path: Path):
    """A reduced output must never be created inside the protected source."""
    source = tmp_path / "project"
    source.mkdir()

    with ReductionWorkspace(source) as workspace:
        with pytest.raises(ValueError, match="outside"):
            workspace.copy_reduced_to(source / "output")


def test_workspace_rejects_an_existing_output_directory(tmp_path: Path):
    """Publication never overwrites an existing directory."""
    source = tmp_path / "project"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    with ReductionWorkspace(source) as workspace:
        with pytest.raises(ValueError, match="already exists"):
            workspace.copy_reduced_to(output)
