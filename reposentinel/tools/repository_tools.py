"""The V0.1 tool surface for later agent integration."""

from __future__ import annotations

from pathlib import Path

from reposentinel.path_utils import resolve_repository_file
from reposentinel.scanner.ast_analyzer import AstAnalyzer
from reposentinel.scanner.repository_scanner import RepositoryScanner


class RepositoryTools:
    """Expose safe, read-only operations against one repository root."""

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize tools for one inspected repository.

        Args:
            repository_root: Directory that all read-only operations may use.

        Raises:
            NotADirectoryError: If ``repository_root`` is not a directory.
        """
        self.scanner = RepositoryScanner(repository_root)
        self.analyzer = AstAnalyzer(self.scanner.root)
        self.root = self.scanner.root

    def list_tree(self) -> list[str]:
        """List repository-relative files in deterministic order.

        Returns:
            Included repository-relative file paths.
        """
        return self.scanner.list_files()

    def read_file(self, path: str | Path) -> str:
        """Read a UTF-8 text file inside the repository.

        Args:
            path: Repository-relative file path.

        Returns:
            File contents with undecodable bytes replaced.

        Raises:
            ValueError: If ``path`` is absolute or escapes the repository.
            FileNotFoundError: If ``path`` is not a regular file.
        """
        file_path, _ = resolve_repository_file(self.root, path)
        return file_path.read_text(encoding="utf-8", errors="replace")

    def search_code(self, keyword: str) -> list[dict[str, object]]:
        """Find a literal string and return line-level evidence.

        Args:
            keyword: Non-empty, case-sensitive string to search for.

        Returns:
            Matches containing repository-relative path, line number, and text.

        Raises:
            ValueError: If ``keyword`` is empty.
        """
        if not keyword:
            raise ValueError("keyword must not be empty")
        matches: list[dict[str, object]] = []
        for relative in self.list_tree():
            try:
                file_path, _ = resolve_repository_file(self.root, relative)
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if keyword in line:
                    matches.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
        return matches

    def get_ast_summary(self, path: str | Path | None = None) -> object:
        """Return one Python AST summary or summaries for all Python files.

        Args:
            path: Optional repository-relative Python file path. If omitted,
                every discovered Python file is analyzed.

        Returns:
            One AST summary dictionary or a list of summary dictionaries.
        """
        if path is not None:
            return self.analyzer.analyze_file(path)
        python_paths = self.scanner.scan().python_paths
        return [self.analyzer.analyze_file(item) for item in python_paths]

    def get_project_summary(self) -> dict[str, object]:
        """Return the repository profile enriched with static AST facts.

        Returns:
            A project summary containing file-level facts, AST totals, and
            no per-file AST summaries. Call ``get_ast_summary`` when detailed
            per-file evidence is needed.
        """
        profile_data = self.scanner.scan()
        profile = profile_data.to_dict()
        class_count = 0
        function_count = 0
        for path in profile_data.python_paths:
            ast_summary = self.analyzer.analyze_file(path)
            class_count += len(ast_summary["classes"])
            function_count += len(ast_summary["functions"])
        profile["classes"] = class_count
        profile["functions"] = function_count
        return profile
