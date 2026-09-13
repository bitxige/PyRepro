"""Create disposable project copies and verify that sources remain unchanged."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReductionWorkspace:
    """Disposable copy of a source project used during reduction.

    Attributes:
        source_root: Original project directory that must remain unchanged.
    """

    source_root: Path
    _initial_digest: str = field(init=False, repr=False)
    _temporary_directory: tempfile.TemporaryDirectory[str] | None = field(
        default=None, init=False, repr=False
    )
    _working_root: Path | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalize and validate the protected source root.

        Raises:
            ValueError: If the source root is not an existing directory.
        """
        self.source_root = self.source_root.expanduser().resolve()
        if not self.source_root.is_dir():
            raise ValueError(f"source root is not a directory: {self.source_root}")
        self._initial_digest = tree_digest(self.source_root)

    def __enter__(self) -> ReductionWorkspace:
        """Copy the protected source into a temporary working directory.

        Returns:
            Active disposable workspace.
        """
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="pyrepro-reducer-"
        )
        self._working_root = Path(self._temporary_directory.name) / "project"
        shutil.copytree(self.source_root, self._working_root)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Remove the temporary workspace after reduction completes."""
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
        self._temporary_directory = None
        self._working_root = None

    @property
    def root(self) -> Path:
        """Return the active temporary project root.

        Raises:
            RuntimeError: If the workspace context is not active.
        """
        if self._working_root is None:
            raise RuntimeError("reduction workspace is not active")
        return self._working_root

    def source_is_unchanged(self) -> bool:
        """Check whether the protected source tree still matches its initial digest.

        Returns:
            Whether the original source tree has not changed.
        """
        return tree_digest(self.source_root) == self._initial_digest

    def copy_reduced_to(self, destination: Path) -> Path:
        """Copy the current reduced workspace to a new output directory.

        Args:
            destination: Non-existing output directory outside the source root.

        Returns:
            Resolved output directory containing the reduced project.

        Raises:
            ValueError: If destination is inside the source root or already exists.
        """
        output = destination.expanduser().resolve()
        try:
            output.relative_to(self.source_root)
        except ValueError:
            pass
        else:
            raise ValueError("output directory must be outside the source root")
        if output.exists():
            raise ValueError(f"output directory already exists: {output}")
        shutil.copytree(self.root, output)
        return output


def tree_digest(root: Path) -> str:
    """Return a deterministic digest of the current tree structure and contents.

    Args:
        root: Existing directory to hash.

    Returns:
        SHA-256 digest of relative paths, entry kinds, and file contents.
    """
    hasher = hashlib.sha256()
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            hasher.update(b"symlink\0" + relative + b"\0")
            hasher.update(path.readlink().as_posix().encode())
        elif path.is_dir():
            hasher.update(b"directory\0" + relative + b"\0")
        elif path.is_file():
            hasher.update(b"file\0" + relative + b"\0")
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(8192), b""):
                    hasher.update(chunk)
    return hasher.hexdigest()
