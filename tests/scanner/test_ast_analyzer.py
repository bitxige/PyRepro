"""Tests for syntax-only Python AST analysis."""

from pyrepro.scanner.ast_analyzer import AstAnalyzer


def test_ast_summary_contains_symbols_and_facts(fixture_repo):
    """Extract classes, methods, arguments, and docstring facts."""
    summary = AstAnalyzer(fixture_repo).analyze_file("src/mod.py")

    assert summary["module_docstring"] is True
    assert summary["imports"] == []
    assert summary["classes"][0]["qualified_name"] == "Thing"
    assert summary["classes"][0]["has_docstring"] is True
    run = next(item for item in summary["functions"] if item["name"] == "run")
    assert run["qualified_name"] == "Thing.run"
    assert run["arguments"] == 2
    assert run["has_docstring"] is False


def test_ast_analyzer_reports_syntax_errors(fixture_repo):
    """Return syntax-error evidence without raising during analysis."""
    path = fixture_repo / "broken.py"
    path.write_text("def broken(:\n", encoding="utf-8")

    summary = AstAnalyzer(fixture_repo).analyze_file("broken.py")

    assert summary["syntax_error"]["message"]
    assert summary["functions"] == []


def test_ast_analyzer_honors_python_source_encoding(fixture_repo):
    """Read a Python file using the encoding declared in its source."""
    path = fixture_repo / "latin1.py"
    path.write_bytes(b"# coding: latin-1\nname = 'caf\xe9'\n")

    summary = AstAnalyzer(fixture_repo).analyze_file("latin1.py")

    assert summary["read_error"] is None
    assert summary["syntax_error"] is None


def test_ast_analyzer_qualifies_nested_scopes(fixture_repo):
    """Include class and function scopes in nested symbol names."""
    path = fixture_repo / "nested.py"
    path.write_text(
        "class Outer:\n"
        "    def method(self):\n"
        "        def inner():\n"
        "            return 1\n"
        "        return inner()\n"
        "\n"
        "def outer():\n"
        "    def inner():\n"
        "        return 2\n"
        "    return inner()\n",
        encoding="utf-8",
    )

    summary = AstAnalyzer(fixture_repo).analyze_file("nested.py")
    names = [item["qualified_name"] for item in summary["functions"]]

    assert names == ["Outer.method", "Outer.method.inner", "outer", "outer.inner"]


def test_ast_analyzer_rejects_path_escape(fixture_repo):
    """Reject AST analysis paths outside the repository root."""
    try:
        AstAnalyzer(fixture_repo).analyze_file("../outside.py")
    except ValueError as error:
        assert "escapes" in str(error)
    else:
        raise AssertionError("path escape was accepted")
