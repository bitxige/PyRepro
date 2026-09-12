"""Tests for Markdown static-profile reports."""

from reposentinel.report.markdown_report import MarkdownReportGenerator
from reposentinel.tools.repository_tools import RepositoryTools


def test_report_contains_profile_and_source_evidence(fixture_repo, tmp_path):
    """Include profile sections and symbol-level evidence in the report."""
    summary = RepositoryTools(fixture_repo).get_project_summary()
    ast_summaries = RepositoryTools(fixture_repo).get_ast_summary()
    destination = tmp_path / "report.md"

    MarkdownReportGenerator().write(summary, destination, ast_summaries)
    report = destination.read_text(encoding="utf-8")

    assert "## Project Overview" in report
    assert "## Overall Assessment" in report
    assert "`src/mod.py`" in report
    assert "`Thing.run`" in report
    assert "Contextual LLM review is intentionally deferred" in report


def test_report_does_not_claim_ast_facts_without_evidence():
    """Describe missing AST evidence instead of claiming no long functions."""
    summary = {
        "project_name": "fixture",
        "total_files": 1,
        "python_files": 1,
        "classes": 0,
        "functions": 0,
        "test_files": 0,
        "python_paths": ["module.py"],
        "has_readme": False,
        "has_pyproject": False,
        "has_requirements": False,
        "has_git": False,
        "has_github_actions": False,
        "has_pre_commit": False,
    }

    report = MarkdownReportGenerator().render(summary)

    assert "AST evidence was not supplied" in report
    assert "No functions at or above" not in report
