"""Inventory a repository without executing or modifying it."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
    ".venv",
}
README_NAMES = {"README", "README.md", "README.rst", "README.txt"}
REQUIREMENTS_NAMES = {"requirements.txt", "requirements-dev.txt"}


def _is_pytest_file(path: str) -> bool:
    """Return whether a filename matches pytest's default test patterns.

    Args:
        path: Repository-relative Python path to classify.

    Returns:
        ``True`` for ``test_*.py`` and ``*_test.py`` files.
    """
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


@dataclass(frozen=True)
class RepositoryProfile:
    """Serializable facts about a repository's files and basic metadata.

    Attributes:
        project_name: Name of the inspected repository directory.
        total_files: Number of included regular files.
        python_files: Number of included Python source files.
        test_files: Number of files identified as Python test files.
        has_readme: Whether a README exists at the repository root.
        has_pyproject: Whether ``pyproject.toml`` exists at the root.
        has_requirements: Whether a requirements file exists at the root.
        has_git: Whether Git metadata exists at the root.
        has_github_actions: Whether a GitHub Actions workflow directory exists.
        has_pre_commit: Whether a pre-commit configuration exists.
        python_paths: Repository-relative Python file paths.
        test_paths: Repository-relative Python test file paths.
        files: All included repository-relative file paths.
    """

    project_name: str
    total_files: int
    python_files: int
    test_files: int
    has_readme: bool
    has_pyproject: bool
    has_requirements: bool
    has_git: bool
    has_github_actions: bool
    has_pre_commit: bool
    python_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the profile.

        Returns:
            A dictionary with list values instead of tuple values for paths.
        """
        result = asdict(self)
        result["python_paths"] = list(self.python_paths)
        result["test_paths"] = list(self.test_paths)
        result["files"] = list(self.files)
        return result


class RepositoryScanner:
    """Collect a read-only file inventory for a local repository."""

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize a scanner for a local repository.

        Args:
            repository_root: Directory to inspect.

        Raises:
            NotADirectoryError: If ``repository_root`` is not a directory.
        """
        root = Path(repository_root).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Repository root is not a directory: {root}")
        self.root = root

    def list_files(self) -> list[str]:
        """Return sorted, repository-relative regular files.

        Returns:
            Included file paths in deterministic POSIX order.

        Common generated directories are skipped. Symlinks are included only
        when their resolved target remains inside the repository.
        """
        files: list[str] = []
        for path in self.root.rglob("*"):
            relative_parts = path.relative_to(self.root).parts
            if any(part in IGNORED_DIRECTORIES for part in relative_parts):
                continue
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(self.root)
            except ValueError:
                continue
            files.append(path.relative_to(self.root).as_posix())
        return sorted(files)

    def scan(self) -> RepositoryProfile:
        """Build a repository profile from the file inventory.

        Returns:
            File-level facts for the configured repository.
        """
        files = self.list_files()
        python_paths = tuple(path for path in files if path.endswith(".py"))
        test_paths = tuple(
            path for path in files if path.endswith(".py") and _is_pytest_file(path)
        )
        top_level_names = {
            Path(path).name for path in files if len(Path(path).parts) == 1
        }
        return RepositoryProfile(
            project_name=self.root.name,
            total_files=len(files),
            python_files=len(python_paths),
            test_files=len(test_paths),
            has_readme=bool(top_level_names & README_NAMES),
            has_pyproject="pyproject.toml" in top_level_names,
            has_requirements=bool(top_level_names & REQUIREMENTS_NAMES),
            has_git=(self.root / ".git").exists(),
            has_github_actions=(self.root / ".github" / "workflows").is_dir(),
            has_pre_commit=(self.root / ".pre-commit-config.yaml").is_file(),
            python_paths=python_paths,
            test_paths=test_paths,
            files=tuple(files),
        )
