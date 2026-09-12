"""Generate a deterministic Markdown profile for V0.1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

LONG_FUNCTION_LINE_THRESHOLD = 20


def _yes_no(value: object) -> str:
    """Format a truthy value for a Markdown presence table.

    Args:
        value: Value whose truthiness should be rendered.

    Returns:
        ``"Yes"`` for truthy values and ``"No"`` otherwise.
    """
    return "Yes" if value else "No"


class MarkdownReportGenerator:
    """Render static facts while explicitly leaving contextual judgement open."""

    def render(
        self,
        summary: dict[str, Any],
        ast_summaries: list[dict[str, Any]] | None = None,
    ) -> str:
        """Return a Markdown report from ``get_project_summary`` output.

        Args:
            summary: Static project summary to render.
            ast_summaries: Optional per-file AST summaries to include as
                evidence. The compact project summary does not contain them.

        Returns:
            Deterministic Markdown containing profile facts and evidence.
        """
        name = summary.get("project_name", "Repository")
        ast_evidence_supplied = ast_summaries is not None
        ast_summaries = [] if ast_summaries is None else ast_summaries
        long_functions = [
            (item["path"], function)
            for item in ast_summaries
            for function in item.get("functions", [])
            if function.get("lines", 0) >= LONG_FUNCTION_LINE_THRESHOLD
        ]
        lines = [
            f"# Software Engineering Review Report: {name}",
            "",
            "> V0.1 static profile. Contextual LLM review is intentionally "
            "deferred to V0.2.",
            "",
            "## Project Overview",
            "",
            f"- Total files: {summary.get('total_files', 0)}",
            f"- Python files: {summary.get('python_files', 0)}",
            f"- Classes: {summary.get('classes', 0)}",
            f"- Functions: {summary.get('functions', 0)}",
            f"- Test files: {summary.get('test_files', 0)}",
            "",
            "| Project signal | Present |",
            "| --- | --- |",
            f"| README | {_yes_no(summary.get('has_readme'))} |",
            f"| pyproject.toml | {_yes_no(summary.get('has_pyproject'))} |",
            f"| requirements file | {_yes_no(summary.get('has_requirements'))} |",
            f"| Git metadata | {_yes_no(summary.get('has_git'))} |",
            f"| GitHub Actions | {_yes_no(summary.get('has_github_actions'))} |",
            f"| pre-commit | {_yes_no(summary.get('has_pre_commit'))} |",
            "",
            "## Overall Assessment",
            "",
            "Not assessed in V0.1. This version reports observable repository "
            "facts; it does not assign a mechanical quality score or make "
            "contextual findings.",
            "",
            "## Main Strengths",
            "",
            "Static inventory and syntax-level evidence are available for "
            "follow-up review.",
            "",
            "## Main Findings",
            "",
            "No prioritised findings are produced by the V0.1 scanner. Counts "
            "and missing project files are evidence for a later review, not "
            "findings by themselves.",
            "",
            "## Architecture & Organization",
            "",
            "### Python files",
            "",
        ]
        lines.extend(f"- `{path}`" for path in summary.get("python_paths", []))
        lines.extend(
            [
                "",
                "## Maintainability",
                "",
                "Static candidates (not judgements):",
                "",
            ]
        )
        if not ast_evidence_supplied:
            lines.append("- AST evidence was not supplied to the report generator.")
        elif long_functions:
            lines.extend(
                f"- `{path}` — `{function['qualified_name']}` at line "
                f"{function['lineno']} ({function['lines']} lines)"
                for path, function in long_functions
            )
        else:
            lines.append(
                "- No functions at or above the "
                f"{LONG_FUNCTION_LINE_THRESHOLD}-line profile threshold."
            )
        lines.extend(
            [
                "",
                "## Documentation",
                "",
                "AST summaries record module, class, and function docstring "
                "presence. Whether documentation is necessary depends on "
                "public API and behavior context and is deferred to V0.2.",
                "",
                "## Testing",
                "",
                f"Detected test files: {summary.get('test_files', 0)}.",
                "Static test-design review is deferred; V0.1 does not execute "
                "tests in the inspected repository.",
                "",
                "## Evidence",
                "",
                (
                    "AST evidence is included below with file paths, symbols, and "
                    "source locations."
                    if ast_evidence_supplied
                    else "AST evidence was not supplied for this report."
                ),
                "",
            ]
        )
        for item in ast_summaries:
            lines.append(f"### `{item['path']}`")
            lines.append("")
            if item.get("read_error"):
                lines.append(f"- Read error: `{item['read_error']}`")
            if item.get("syntax_error"):
                lines.append(f"- Syntax error: `{item['syntax_error']}`")
            for cls in item.get("classes", []):
                lines.append(
                    f"- Class `{cls['qualified_name']}` — line {cls['lineno']}, "
                    f"{cls['lines']} lines, docstring: {_yes_no(cls['has_docstring'])}"
                )
            for function in item.get("functions", []):
                lines.append(
                    f"- Function `{function['qualified_name']}` — line "
                    f"{function['lineno']}, {function['lines']} lines, "
                    f"{function['arguments']} args, docstring: "
                    f"{_yes_no(function['has_docstring'])}"
                )
            if (
                not item.get("classes")
                and not item.get("functions")
                and not item.get("read_error")
                and not item.get("syntax_error")
            ):
                lines.append("- No classes or functions detected.")
            lines.append("")
        lines.extend(
            [
                "## Final Recommendation",
                "",
                "Use this profile as input to the V0.2 read-only Agent review. "
                "Do not interpret the profile alone as merge readiness.",
                "",
            ]
        )
        return "\n".join(lines)

    def write(
        self,
        summary: dict[str, Any],
        output_path: str | Path,
        ast_summaries: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Write a report to an explicitly selected output path.

        Args:
            summary: Static project summary to render.
            output_path: Destination path selected by the calling layer.
            ast_summaries: Optional per-file AST summaries to include.

        Returns:
            The created destination path.
        """
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            self.render(summary, ast_summaries=ast_summaries), encoding="utf-8"
        )
        return destination
