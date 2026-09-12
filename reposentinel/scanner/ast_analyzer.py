"""Safe, syntax-only summaries for Python files."""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

from reposentinel.path_utils import resolve_repository_file


class AstAnalyzer:
    """Extract structural facts from Python source without importing it."""

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize an analyzer for a local repository.

        Args:
            repository_root: Directory containing the Python files to inspect.

        Raises:
            NotADirectoryError: If ``repository_root`` is not a directory.
        """
        self.root = Path(repository_root).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"Repository root is not a directory: {self.root}")

    @staticmethod
    def _arguments_count(arguments: ast.arguments) -> int:
        """Count positional, keyword-only, variadic, and keyword arguments.

        Args:
            arguments: AST argument container for one function.

        Returns:
            Number of declared arguments, including ``*args`` and ``**kwargs``.
        """
        return (
            len(arguments.posonlyargs)
            + len(arguments.args)
            + len(arguments.kwonlyargs)
            + int(arguments.vararg is not None)
            + int(arguments.kwarg is not None)
        )

    def analyze_file(self, path: str | Path) -> dict[str, object]:
        """Return classes, functions, imports, and docstring facts for a file.

        Args:
            path: Repository-relative Python file path.

        Returns:
            A dictionary containing syntax-only structural facts and any read
            or syntax error that prevented analysis.

        Raises:
            ValueError: If ``path`` escapes the repository root.
            FileNotFoundError: If ``path`` is not a regular file.
        """
        file_path, relative = resolve_repository_file(self.root, path)
        result: dict[str, object] = {
            "path": relative,
            "lines": 0,
            "read_error": None,
            "syntax_error": None,
            "module_docstring": False,
            "classes": [],
            "functions": [],
            "imports": [],
        }
        try:
            with tokenize.open(file_path) as source_file:
                source = source_file.read()
        except (SyntaxError, UnicodeDecodeError) as error:
            result["read_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            return result
        result["lines"] = len(source.splitlines())
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as error:
            result["syntax_error"] = {
                "line": error.lineno,
                "offset": error.offset,
                "message": error.msg,
            }
            return result

        result["module_docstring"] = ast.get_docstring(tree) is not None
        classes: list[dict[str, object]] = []
        functions: list[dict[str, object]] = []
        imports: list[str] = []

        class Visitor(ast.NodeVisitor):
            """Collect selected AST nodes while tracking lexical scopes."""

            def __init__(self) -> None:
                """Initialize traversal state for nested lexical scopes."""
                self.scope_stack: list[str] = []

            def visit_Import(self, node: ast.Import) -> None:
                """Collect a plain import statement."""
                imports.extend(alias.name for alias in node.names)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                """Collect a relative or absolute from-import statement."""
                module = "." * node.level + (node.module or "")
                imports.extend(f"{module}:{alias.name}" for alias in node.names)
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                """Record a class and visit its methods and nested classes."""
                qualified_name = ".".join([*self.scope_stack, node.name])
                classes.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
                        "is_public_name": not node.name.startswith("_"),
                        "has_docstring": ast.get_docstring(node) is not None,
                    }
                )
                self.scope_stack.append(node.name)
                self.generic_visit(node)
                self.scope_stack.pop()

            def _visit_function(
                self, node: ast.AsyncFunctionDef | ast.FunctionDef
            ) -> None:
                """Record a synchronous or asynchronous function node."""
                prefix = ".".join(self.scope_stack)
                qualified_name = ".".join(filter(None, [prefix, node.name]))
                functions.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
                        "arguments": AstAnalyzer._arguments_count(node.args),
                        "is_public_name": not node.name.startswith("_"),
                        "async": isinstance(node, ast.AsyncFunctionDef),
                        "has_docstring": ast.get_docstring(node) is not None,
                    }
                )
                self.scope_stack.append(node.name)
                self.generic_visit(node)
                self.scope_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                """Visit a synchronous function definition."""
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                """Visit an asynchronous function definition."""
                self._visit_function(node)

        Visitor().visit(tree)
        result["classes"] = classes
        result["functions"] = functions
        result["imports"] = sorted(set(imports))
        return result
