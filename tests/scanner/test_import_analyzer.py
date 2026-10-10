"""Tests for read-only, conservative Python import analysis."""

from pathlib import Path

from pyrepro.reproducer.__main__ import main
from pyrepro.reproducer.workspace import tree_digest
from pyrepro.scanner.import_analyzer import ImportAnalyzer, format_import_analysis


def test_import_analyzer_discovers_flat_test_import_candidates(tmp_path: Path):
    """Find unused direct test bindings while retaining used bindings."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/core.py",
        "class Needed:\n    pass\n\nclass Unused:\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_core.py",
        "from pkg.core import Needed, Unused\n\n"
        "def test_needed():\n"
        "    assert Needed is not None\n",
    )
    source_digest = tree_digest(tmp_path)

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert analysis.layout.kind == "flat"
    assert analysis.layout.source_roots == (".",)
    assert analysis.layout.package_modules == ("pkg",)
    assert _candidate_names(analysis) == {("test_import", "Unused")}
    assert _skip_reasons(analysis, "Needed") == {"binding_used"}
    assert tree_digest(tmp_path) == source_digest


def test_import_analyzer_handles_src_and_relative_imports(tmp_path: Path):
    """Resolve namespace src modules and package-relative test imports."""
    _write(tmp_path, "src/acme/extra.py", "class Extra:\n    pass\n")
    _write(tmp_path, "tests/__init__.py", "")
    _write(tmp_path, "tests/helpers.py", "class Helper:\n    pass\n")
    _write(
        tmp_path,
        "tests/test_relative.py",
        "from acme.extra import Extra\n"
        "from .helpers import Helper\n\n"
        "def test_placeholder():\n"
        "    assert True\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert analysis.layout.kind == "src"
    assert analysis.layout.source_roots == ("src", ".")
    assert {
        (candidate.bound_name, candidate.imported_module)
        for candidate in analysis.test_import_candidates
    } == {("Extra", "acme.extra"), ("Helper", "tests.helpers")}
    assert analysis.unresolved_imports == ()


def test_import_analyzer_finds_unused_reexports_but_preserves_static_consumers(
    tmp_path: Path,
):
    """Propose only package re-exports without observed static consumers."""
    _write(
        tmp_path,
        "src/acme/__init__.py",
        "from .exports import Kept, Removable\n",
    )
    _write(
        tmp_path,
        "src/acme/exports.py",
        "class Kept:\n    pass\n\nclass Removable:\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_exports.py",
        "from acme import Kept\n\ndef test_kept():\n    assert Kept is not None\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert _candidate_names(analysis) == {("reexport", "Removable")}
    assert "reexport_used" in _skip_reasons(analysis, "Kept")


def test_import_analyzer_recognizes_function_local_reexport_consumers(
    tmp_path: Path,
):
    """Do not propose a re-export imported and used inside a function."""
    _write(tmp_path, "pkg/__init__.py", "from .exports import Kept\n")
    _write(tmp_path, "pkg/exports.py", "class Kept:\n    pass\n")
    _write(
        tmp_path,
        "consumer.py",
        "def build():\n    from pkg import Kept\n    return Kept()\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert not analysis.reexport_candidates
    assert "reexport_used" in _skip_reasons(analysis, "Kept")


def test_import_analyzer_skips_dynamic_wildcard_and_side_effect_risks(
    tmp_path: Path,
):
    """Conservatively skip uncertain imports instead of proposing deletion."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/safe.py", "class Safe:\n    pass\n")
    _write(
        tmp_path,
        "pkg/side_effect.py",
        "registry = []\nregistry.append('loaded')\n\nclass SideEffect:\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_risks.py",
        "import importlib\n"
        "from pkg.safe import Safe\n"
        "from pkg.side_effect import SideEffect\n"
        "from pkg.safe import *\n\n"
        "importlib.import_module('pkg.safe')\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert not analysis.test_import_candidates
    assert _skip_reasons(analysis, "Safe") == {"dynamic_import"}
    assert _skip_reasons(analysis, "SideEffect") == {"dynamic_import"}
    assert _skip_reasons(analysis, None) == {"wildcard_import"}


def test_import_analyzer_marks_side_effects_without_dynamic_imports(tmp_path: Path):
    """Expose an obvious import-time side effect as a conservative skip."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/side_effect.py",
        "events = []\nevents.append('registered')\n\nclass SideEffect:\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_side_effect.py",
        "from pkg.side_effect import SideEffect\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert _skip_reasons(analysis, "SideEffect") == {"side_effect_risk"}


def test_import_analyzer_traces_import_time_side_effect_dependencies(tmp_path: Path):
    """Skip a wrapper whose own top-level import has observable side effects."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/registration.py",
        "events = []\nevents.append('registered')\n",
    )
    _write(
        tmp_path,
        "pkg/wrapper.py",
        "from . import registration\n\nclass Wrapper:\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_wrapper.py",
        "from pkg.wrapper import Wrapper\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert _skip_reasons(analysis, "Wrapper") == {"side_effect_risk"}


def test_import_analyzer_skips_public_and_unresolved_package_imports(
    tmp_path: Path,
):
    """Keep __all__ exports and unresolved internal modules out of candidates."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        "from .items import Public\n__all__ = ['Public']\n",
    )
    _write(tmp_path, "pkg/items.py", "class Public:\n    pass\n")
    _write(
        tmp_path,
        "tests/test_imports.py",
        "from pkg.missing import Missing\n",
    )

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert _skip_reasons(analysis, "Public") == {"exported_via_all"}
    assert _skip_reasons(analysis, "Missing") == {"unresolved_internal_import"}
    assert analysis.unresolved_imports == ("pkg.missing",)


def test_import_analyzer_reports_unparsable_files_and_does_not_modify_source(
    tmp_path: Path,
):
    """Record parse failures as skips rather than inferring a removable import."""
    _write(tmp_path, "tests/test_broken.py", "def broken(:\n")
    source_digest = tree_digest(tmp_path)

    analysis = ImportAnalyzer(tmp_path).analyze()

    assert analysis.unparsable_files == ("tests/test_broken.py",)
    assert _skip_reasons(analysis, None) == {"unparsable"}
    assert tree_digest(tmp_path) == source_digest


def test_cli_analyze_imports_reports_candidates_without_executing_reduction(
    tmp_path: Path, capsys
):
    """Expose read-only candidate discovery through the public CLI."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/ballast.py", "class Ballast:\n    pass\n")
    _write(
        tmp_path,
        "tests/test_cli.py",
        "from pkg.ballast import Ballast\n",
    )
    source_digest = tree_digest(tmp_path)

    status = main(["analyze-imports", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Import analysis" in captured.out
    assert "Candidate test imports: 1" in captured.out
    assert "No files modified." in captured.out
    assert "No Oracle executions." in captured.out
    assert tree_digest(tmp_path) == source_digest


def test_import_analysis_format_explains_candidates_and_skips(tmp_path: Path):
    """Keep the user-facing report explicit about read-only analysis limits."""
    _write(tmp_path, "tests/test_empty.py", "")

    report = format_import_analysis(ImportAnalyzer(tmp_path).analyze())

    assert "Candidates" in report
    assert "Conservative skips" in report
    assert "No files modified." in report


def _candidate_names(analysis) -> set[tuple[str, str]]:
    return {(candidate.kind, candidate.bound_name) for candidate in analysis.candidates}


def _skip_reasons(analysis, bound_name: str | None) -> set[str]:
    return {skip.reason for skip in analysis.skips if skip.bound_name == bound_name}


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
