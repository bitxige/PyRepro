"""Shared path validation for inspected repositories."""

from __future__ import annotations

from pathlib import Path


def resolve_repository_file(
    repository_root: str | Path, path: str | Path
) -> tuple[Path, str]:
    """Resolve a repository-relative file while enforcing the read boundary.

    Args:
        repository_root: Root directory of the inspected repository.
        path: Relative path of the file to resolve.

    Returns:
        The resolved filesystem path and its repository-relative POSIX path.

    Raises:
        NotADirectoryError: If ``repository_root`` is not a directory.
        ValueError: If ``path`` is absolute or escapes the repository root.
        FileNotFoundError: If ``path`` is not a regular file.

    The returned tuple contains the resolved filesystem path and its
    repository-relative POSIX path. Absolute paths, traversal, escaping
    symlinks, directories, and missing files are rejected.
    """
    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {root}")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError("Only repository-relative paths are allowed")
    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes the repository root") from exc
    if not resolved.is_file():
        raise FileNotFoundError(str(path))
    return resolved, relative.as_posix()
