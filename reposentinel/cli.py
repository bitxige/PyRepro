"""Command-line entry point for a V0.1 repository profile."""

from __future__ import annotations

import argparse
from pathlib import Path

from reposentinel.report.markdown_report import MarkdownReportGenerator
from reposentinel.tools.repository_tools import RepositoryTools


def main() -> int:
    """Scan a repository and write a Markdown profile.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description="Create a RepoSentinel V0.1 profile")
    parser.add_argument("repository", type=Path, help="local Python repository")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("reports") / "repository-profile.md",
        help="Markdown output path (default: reports/repository-profile.md)",
    )
    args = parser.parse_args()
    tools = RepositoryTools(args.repository)
    destination = args.output.expanduser().resolve()
    try:
        destination.relative_to(tools.root)
    except ValueError:
        pass
    else:
        parser.error("output must be outside the inspected repository")
    summary = tools.get_project_summary()
    ast_summaries = tools.get_ast_summary()
    destination = MarkdownReportGenerator().write(
        summary, destination, ast_summaries=ast_summaries
    )
    print(f"Wrote {destination}")
    return 0
