"""Read-only discovery of conservative Python import-pruning candidates."""

from __future__ import annotations

import ast
import tokenize
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyrepro.scanner.repository_scanner import RepositoryProfile, RepositoryScanner


@dataclass(frozen=True)
class RepositoryLayout:
    """Static facts about Python source roots and conventional test modules.

    Attributes:
        kind: ``"src"`` when the repository contains Python under ``src/``;
            otherwise ``"flat"``.
        source_roots: Repository-relative Python source-root directories. ``.``
            denotes the repository root.
        package_modules: Dotted module names backed by ``__init__.py`` files.
        test_paths: Conventional pytest-style test module paths.
    """

    kind: str
    source_roots: tuple[str, ...]
    package_modules: tuple[str, ...]
    test_paths: tuple[str, ...]


@dataclass(frozen=True)
class ImportCandidate:
    """One statically unused import binding proposed for later verification.

    Attributes:
        kind: Candidate category: ``"test_import"`` or ``"reexport"``.
        path: Repository-relative source path containing the import binding.
        line: One-based source line of the import statement.
        bound_name: Name introduced in the containing module.
        imported_module: Resolved module targeted by the import statement.
        imported_name: Name requested from ``imported_module``, if applicable.
        reason: Explanation of why static analysis proposed this binding.
        all_line: Line of a static ``__all__`` declaration that must be kept in
            sync if this re-export is later pruned. ``None`` means that no
            accompanying ``__all__`` edit is required.
        risk_reason: Optional static risk that a later batch verifier must
            report and prioritize conservatively. It never authorizes a source
            edit without execution validation.
    """

    kind: str
    path: str
    line: int
    bound_name: str
    imported_module: str
    imported_name: str | None
    reason: str
    all_line: int | None = None
    risk_reason: str | None = None


@dataclass(frozen=True)
class ImportSkip:
    """An import analysis decision that intentionally does not propose deletion.

    Attributes:
        path: Repository-relative source path containing the skipped import.
        line: One-based source line, when syntax parsing reached an import.
        bound_name: Name that would have been considered, when applicable.
        reason: Stable conservative reason code.
        detail: Human-readable context for the reason.
    """

    path: str
    line: int | None
    bound_name: str | None
    reason: str
    detail: str


@dataclass(frozen=True)
class ImportAnalysis:
    """Read-only repository import analysis result.

    Attributes:
        root: Resolved repository root.
        profile: Deterministic repository file inventory.
        layout: Python source-root and test-module facts.
        candidates: All candidate import bindings, without source edits.
        skips: Conservative skips and parse failures explaining omissions.
        unresolved_imports: Imports that appear internal but cannot be resolved
            unambiguously to one repository module.
        unparsable_files: Python files skipped because they could not be read or
            parsed as Python source.
    """

    root: Path
    profile: RepositoryProfile
    layout: RepositoryLayout
    candidates: tuple[ImportCandidate, ...]
    skips: tuple[ImportSkip, ...]
    unresolved_imports: tuple[str, ...]
    unparsable_files: tuple[str, ...]

    @property
    def test_import_candidates(self) -> tuple[ImportCandidate, ...]:
        """Return candidate bindings discovered in conventional test modules."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.kind == "test_import"
        )

    @property
    def reexport_candidates(self) -> tuple[ImportCandidate, ...]:
        """Return candidate bindings discovered in package initializers."""
        return tuple(
            candidate for candidate in self.candidates if candidate.kind == "reexport"
        )


@dataclass(frozen=True)
class PytestEntry:
    """One statically resolved pytest test-function entry point.

    Attributes:
        node_id: Original pytest node ID supplied by the user.
        path: Repository-relative test module path.
        class_name: Containing test class for a method node, if supplied.
        function_name: Target test function or method name.
    """

    node_id: str
    path: str
    class_name: str | None
    function_name: str


@dataclass(frozen=True)
class TargetImportAnalysis:
    """Read-only import candidates scoped to one statically resolved test.

    This result is intentionally a candidate report, not a proof that a source
    edit preserves the target failure. A later execution-verified stage must
    validate every proposed edit in a disposable workspace.

    Attributes:
        base: Repository-level P5.1 analysis facts.
        entry: Resolved target pytest entry.
        retained_bindings: Top-level test-module bindings used by the target,
            statically reachable local helpers or fixtures, decorators, or
            module-level execution context.
        candidates: Target-scoped import and re-export proposals.
        skips: Conservative omissions with stable reason codes.
    """

    base: ImportAnalysis
    entry: PytestEntry
    retained_bindings: tuple[str, ...]
    candidates: tuple[ImportCandidate, ...]
    skips: tuple[ImportSkip, ...]

    @property
    def test_import_candidates(self) -> tuple[ImportCandidate, ...]:
        """Return target-scoped test-module import candidates."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.kind == "target_test_import"
        )

    @property
    def reexport_candidates(self) -> tuple[ImportCandidate, ...]:
        """Return target-scoped package re-export candidates."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.kind == "target_reexport"
        )


class ImportAnalyzer:
    """Analyze Python imports without importing, executing, or editing source.

    The analyzer supports flat and ``src`` layouts, ordinary packages, and
    namespace-style source directories. It proposes only direct top-level test
    imports and package ``__init__.py`` re-exports whose bound names have no
    statically observed use. Dynamic imports, wildcard imports, unresolved
    modules, and modules with obvious top-level side effects are skipped.

    Args:
        repository_root: Local repository directory to inspect read-only.
    """

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize a read-only analyzer for one repository."""
        self.root = Path(repository_root).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"repository root is not a directory: {self.root}")

    def analyze(self) -> ImportAnalysis:
        """Return deterministic candidates and conservative skip reasons.

        Returns:
            A syntax-only analysis result. This method never executes project
            code, invokes an Oracle, or modifies the repository.
        """
        profile, layout, index, facts, skips = self._collect_facts()

        used_reexports, wildcard_reexports, dynamic_reexports = _reexport_uses(
            facts.values(), index
        )
        candidates: list[ImportCandidate] = []
        unresolved: set[str] = set()
        for fact in facts.values():
            _discover_test_candidates(
                fact,
                layout,
                index,
                facts,
                candidates,
                skips,
                unresolved,
            )
            _discover_reexport_candidates(
                fact,
                index,
                facts,
                used_reexports,
                wildcard_reexports,
                dynamic_reexports,
                candidates,
                skips,
                unresolved,
            )

        return ImportAnalysis(
            root=self.root,
            profile=profile,
            layout=layout,
            candidates=tuple(_sorted_candidates(candidates)),
            skips=tuple(_sorted_skips(skips)),
            unresolved_imports=tuple(sorted(unresolved)),
            unparsable_files=tuple(
                sorted(skip.path for skip in skips if skip.reason == "unparsable")
            ),
        )

    def analyze_pytest_node(self, node_id: str) -> TargetImportAnalysis:
        """Propose read-only import candidates for one pytest function node.

        Only conventional function or method node IDs of the form
        ``path/to/test_file.py::test_name`` or
        ``path/to/test_file.py::TestClass::test_name`` are supported. Custom
        pytest collectors and arbitrary reproduction commands are deliberately
        not inferred. The result does not execute project code or edit source.

        Args:
            node_id: Explicit pytest node ID naming the target test function.

        Returns:
            Syntax-derived candidates scoped to the target entry and its
            statically reachable same-module helper and fixture functions.

        Raises:
            ValueError: If the node ID does not name a resolvable Python test
                function or method within this repository.
        """
        profile, layout, index, facts, parse_skips = self._collect_facts()
        base = self._analysis_from_facts(profile, layout, index, facts, parse_skips)
        entry = _parse_pytest_entry(node_id, profile)
        tree = _read_syntax_tree(self.root, entry.path)
        context = _target_context(tree, entry)
        target_fact = facts.get(entry.path)
        if target_fact is None:
            raise ValueError(f"target test module could not be parsed: {entry.path}")

        candidates: list[ImportCandidate] = []
        skips: list[ImportSkip] = []
        unresolved: set[str] = set()
        for binding in target_fact.imports:
            if not binding.is_top_level:
                continue
            _consider_binding(
                "target_test_import",
                target_fact,
                binding,
                index,
                facts,
                candidates,
                skips,
                unresolved,
                used_names=context.required_names,
                candidate_reason="unused_for_target_entry",
                used_skip_reason="target_entry_used",
                used_skip_detail=(
                    "binding is used by the target entry, a statically reachable "
                    "local helper or fixture, decorator, or module-level context"
                ),
                allow_side_effect_risk=True,
            )

        required_reexports, relevant_packages = _target_import_surface(
            target_fact, context, index
        )
        for fact in facts.values():
            _discover_target_reexport_candidates(
                fact,
                relevant_packages,
                required_reexports,
                index,
                facts,
                candidates,
                skips,
                unresolved,
            )
        return TargetImportAnalysis(
            base=base,
            entry=entry,
            retained_bindings=tuple(
                sorted(
                    binding.bound_name
                    for binding in target_fact.imports
                    if binding.is_top_level
                    and binding.bound_name is not None
                    and binding.bound_name in context.required_names
                )
            ),
            candidates=tuple(_sorted_candidates(candidates)),
            skips=tuple(_sorted_skips(skips)),
        )

    def _collect_facts(
        self,
    ) -> tuple[
        RepositoryProfile,
        RepositoryLayout,
        _ModuleIndex,
        dict[str, _ModuleFacts],
        list[ImportSkip],
    ]:
        """Scan one repository and parse its Python files without execution."""
        profile = RepositoryScanner(self.root).scan()
        layout = _discover_layout(profile)
        index = _ModuleIndex(profile.python_paths, layout.source_roots)
        facts: dict[str, _ModuleFacts] = {}
        skips: list[ImportSkip] = []
        for path in profile.python_paths:
            module_name = index.module_for_path(path)
            fact, parse_skip = _read_module_facts(self.root, path, module_name)
            if parse_skip is not None:
                skips.append(parse_skip)
            elif fact is not None:
                facts[path] = fact
        return profile, layout, index, facts, skips

    def _analysis_from_facts(
        self,
        profile: RepositoryProfile,
        layout: RepositoryLayout,
        index: _ModuleIndex,
        facts: dict[str, _ModuleFacts],
        skips: list[ImportSkip],
    ) -> ImportAnalysis:
        """Build the unchanged P5.1 repository result from parsed facts."""
        skips = list(skips)
        used_reexports, wildcard_reexports, dynamic_reexports = _reexport_uses(
            facts.values(), index
        )
        candidates: list[ImportCandidate] = []
        unresolved: set[str] = set()
        for fact in facts.values():
            _discover_test_candidates(
                fact,
                layout,
                index,
                facts,
                candidates,
                skips,
                unresolved,
            )
            _discover_reexport_candidates(
                fact,
                index,
                facts,
                used_reexports,
                wildcard_reexports,
                dynamic_reexports,
                candidates,
                skips,
                unresolved,
            )
        return ImportAnalysis(
            root=self.root,
            profile=profile,
            layout=layout,
            candidates=tuple(_sorted_candidates(candidates)),
            skips=tuple(_sorted_skips(skips)),
            unresolved_imports=tuple(sorted(unresolved)),
            unparsable_files=tuple(
                sorted(skip.path for skip in skips if skip.reason == "unparsable")
            ),
        )


def format_import_analysis(analysis: ImportAnalysis) -> str:
    """Format a concise, human-readable read-only import analysis report.

    Args:
        analysis: Completed static import analysis.

    Returns:
        Multi-line report with candidates and conservative skips.
    """
    lines = [
        "Import analysis",
        "---------------",
        f"Repository layout: {analysis.layout.kind}",
        "Source roots: " + ", ".join(analysis.layout.source_roots),
        f"Python files: {analysis.profile.python_files}",
        f"Test modules: {len(analysis.layout.test_paths)}",
        f"Package modules: {len(analysis.layout.package_modules)}",
        f"Candidate test imports: {len(analysis.test_import_candidates)}",
        f"Candidate re-exports: {len(analysis.reexport_candidates)}",
        f"Conservative skips: {len(analysis.skips)}",
        f"Unresolved imports: {len(analysis.unresolved_imports)}",
        f"Unparsable files: {len(analysis.unparsable_files)}",
        "",
        "Candidates",
        "----------",
    ]
    if analysis.candidates:
        lines.extend(
            "- "
            f"{candidate.kind} {candidate.path}:{candidate.line} "
            f"{candidate.bound_name} from {candidate.imported_module} "
            f"({candidate.reason})"
            for candidate in analysis.candidates
        )
    else:
        lines.append("none")
    lines.extend(["", "Conservative skips", "------------------"])
    if analysis.skips:
        lines.extend(
            "- "
            f"{skip.path}:{skip.line if skip.line is not None else '-'} "
            f"{skip.bound_name or '-'} ({skip.reason}: {skip.detail})"
            for skip in analysis.skips
        )
    else:
        lines.append("none")
    lines.extend(["", "No files modified.", "No Oracle executions."])
    return "\n".join(lines)


def format_target_import_analysis(analysis: TargetImportAnalysis) -> str:
    """Format a target-scoped, read-only import-candidate report.

    Args:
        analysis: Static candidates for one explicitly named pytest test.

    Returns:
        Multi-line report describing retained bindings, candidates, and
        conservative skips. It always states that no Oracle was run.
    """
    lines = [
        "Target import analysis",
        "----------------------",
        f"Target pytest node: {analysis.entry.node_id}",
        f"Repository layout: {analysis.base.layout.kind}",
        "Retained target bindings: "
        + (", ".join(analysis.retained_bindings) or "none"),
        f"Candidate target imports: {len(analysis.test_import_candidates)}",
        f"Candidate target re-exports: {len(analysis.reexport_candidates)}",
        f"Conservative skips: {len(analysis.skips)}",
        "",
        "Candidates",
        "----------",
    ]
    if analysis.candidates:
        lines.extend(
            "- "
            f"{candidate.kind} {candidate.path}:{candidate.line} "
            f"{candidate.bound_name} from {candidate.imported_module} "
            f"({candidate.reason}"
            + (
                f"; update __all__ at line {candidate.all_line}"
                if candidate.all_line is not None
                else ""
            )
            + (
                f"; risk: {candidate.risk_reason}"
                if candidate.risk_reason is not None
                else ""
            )
            + ")"
            for candidate in analysis.candidates
        )
    else:
        lines.append("none")
    lines.extend(["", "Conservative skips", "------------------"])
    if analysis.skips:
        lines.extend(
            "- "
            f"{skip.path}:{skip.line if skip.line is not None else '-'} "
            f"{skip.bound_name or '-'} ({skip.reason}: {skip.detail})"
            for skip in analysis.skips
        )
    else:
        lines.append("none")
    lines.extend(
        [
            "",
            "No files modified.",
            "No Oracle executions.",
        ]
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class _ImportBinding:
    path: str
    line: int
    bound_name: str | None
    imported_module: str | None
    imported_name: str | None
    is_star: bool
    is_relative: bool
    is_top_level: bool


@dataclass(frozen=True)
class _ModuleFacts:
    path: str
    module_name: str | None
    is_initializer: bool
    imports: tuple[_ImportBinding, ...]
    loaded_names: frozenset[str]
    attribute_uses: frozenset[tuple[str, str]]
    dynamic_import: bool
    dynamic_attribute_access: frozenset[str]
    exported_names: frozenset[str]
    dynamic_all: bool
    static_all_lines: tuple[int, ...]
    top_level_side_effect_risk: bool


class _ModuleIndex:
    """Map repository paths to unambiguous dotted module names."""

    def __init__(
        self, python_paths: Iterable[str], source_roots: Iterable[str]
    ) -> None:
        self._path_modules: dict[str, str | None] = {}
        modules: dict[str, list[str]] = defaultdict(list)
        roots = tuple(source_roots)
        for path in python_paths:
            module = _module_name(path, roots)
            self._path_modules[path] = module
            if module is not None:
                modules[module].append(path)
        self._modules = {
            module: paths[0] if len(paths) == 1 else None
            for module, paths in modules.items()
        }

    def module_for_path(self, path: str) -> str | None:
        return self._path_modules[path]

    def path_for_module(self, module: str) -> str | None:
        return self._modules.get(module)

    def is_internal_prefix(self, module: str) -> bool:
        first = module.split(".", maxsplit=1)[0]
        return any(name.split(".", maxsplit=1)[0] == first for name in self._modules)

    def side_effect_free(self, module: str, facts: dict[str, _ModuleFacts]) -> bool:
        parts = module.split(".")
        for length in range(1, len(parts) + 1):
            parent = ".".join(parts[:length])
            if self.path_for_module(parent) is None:
                continue
            if not self._module_is_side_effect_free(parent, facts, set()):
                return False
        return True

    def _module_is_side_effect_free(
        self,
        module: str,
        facts: dict[str, _ModuleFacts],
        visiting: set[str],
    ) -> bool:
        """Conservatively inspect one module's import-time dependency surface."""
        if module in visiting:
            return True
        path = self.path_for_module(module)
        if path is None:
            return False
        fact = facts.get(path, _UNKNOWN_FACTS)
        if fact.top_level_side_effect_risk:
            return False
        visiting.add(module)
        try:
            for binding in fact.imports:
                if not binding.is_top_level:
                    continue
                imported_module = self.binding_module(binding)
                if binding.is_star or imported_module is None:
                    return False
                if self.path_for_module(imported_module) is None:
                    # An external dependency can have arbitrary runtime
                    # behavior, but it is not evidence that this repository
                    # module itself has an *obvious* import-time side effect.
                    # Later execution validation remains mandatory for every
                    # candidate proposed through this module.
                    continue
                if not self._module_is_side_effect_free(
                    imported_module, facts, visiting
                ):
                    return False
        finally:
            visiting.remove(module)
        return True

    def binding_module(self, binding: _ImportBinding) -> str | None:
        """Return the concrete internal module loaded by one binding when known."""
        if binding.imported_module is None:
            return None
        if binding.imported_name is not None:
            submodule = f"{binding.imported_module}.{binding.imported_name}"
            if self.path_for_module(submodule) is not None:
                return submodule
        return binding.imported_module


_UNKNOWN_FACTS = _ModuleFacts(
    path="",
    module_name=None,
    is_initializer=False,
    imports=(),
    loaded_names=frozenset(),
    attribute_uses=frozenset(),
    dynamic_import=False,
    dynamic_attribute_access=frozenset(),
    exported_names=frozenset(),
    dynamic_all=False,
    static_all_lines=(),
    top_level_side_effect_risk=True,
)


def _discover_layout(profile: RepositoryProfile) -> RepositoryLayout:
    source_roots = (
        ("src",)
        if any(path.startswith("src/") for path in profile.python_paths)
        else ()
    )
    if any(not path.startswith("src/") for path in profile.python_paths):
        source_roots += (".",)
    if not source_roots:
        source_roots = (".",)
    package_modules = tuple(
        module
        for path in profile.python_paths
        if Path(path).name == "__init__.py"
        if (module := _module_name(path, source_roots)) is not None
    )
    return RepositoryLayout(
        kind="src" if "src" in source_roots else "flat",
        source_roots=source_roots,
        package_modules=tuple(sorted(package_modules)),
        test_paths=profile.test_paths,
    )


def _module_name(path: str, source_roots: Iterable[str]) -> str | None:
    parts = list(Path(path).with_suffix("").parts)
    if not parts:
        return None
    if "src" in source_roots and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or None


def _read_module_facts(
    root: Path, path: str, module_name: str | None
) -> tuple[_ModuleFacts | None, ImportSkip | None]:
    source_path = root / path
    try:
        with tokenize.open(source_path) as source_file:
            tree = ast.parse(source_file.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        return None, ImportSkip(path, None, None, "unparsable", str(error))
    collector = _FactCollector(path, module_name)
    collector.visit(tree)
    return collector.build(), None


class _FactCollector(ast.NodeVisitor):
    """Collect syntax-only facts for one module."""

    def __init__(self, path: str, module_name: str | None) -> None:
        self.path = path
        self.module_name = module_name
        self.imports: list[_ImportBinding] = []
        self.loaded_names: set[str] = set()
        self.attribute_uses: set[tuple[str, str]] = set()
        self.dynamic_import = False
        self.dynamic_attribute_access: set[str] = set()
        self.exported_names: set[str] = set()
        self.dynamic_all = False
        self.static_all_lines: list[int] = []
        self.top_level_side_effect_risk = False

    def build(self) -> _ModuleFacts:
        return _ModuleFacts(
            path=self.path,
            module_name=self.module_name,
            is_initializer=Path(self.path).name == "__init__.py",
            imports=tuple(self.imports),
            loaded_names=frozenset(self.loaded_names),
            attribute_uses=frozenset(self.attribute_uses),
            dynamic_import=self.dynamic_import,
            dynamic_attribute_access=frozenset(self.dynamic_attribute_access),
            exported_names=frozenset(self.exported_names),
            dynamic_all=self.dynamic_all,
            static_all_lines=tuple(self.static_all_lines),
            top_level_side_effect_risk=self.top_level_side_effect_risk,
        )

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            self._visit_top_level(statement)

    def _visit_top_level(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            self._collect_import(node, is_top_level=True)
            return
        if _is_static_all_assignment(node):
            names = _static_all_names(node)
            if names is None:
                self.dynamic_all = True
            else:
                self.exported_names.update(names)
                self.static_all_lines.append(node.lineno)
            return
        if _is_safe_top_level_statement(node):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                self.generic_visit(node)
            return
        self.top_level_side_effect_risk = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Collect a non-top-level import for re-export consumer analysis."""
        self._collect_import(node, is_top_level=False)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Collect a non-top-level from-import for consumer analysis."""
        self._collect_import(node, is_top_level=False)

    def _collect_import(
        self, node: ast.Import | ast.ImportFrom, *, is_top_level: bool
    ) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.imports.append(
                    _ImportBinding(
                        path=self.path,
                        line=node.lineno,
                        bound_name=alias.asname or alias.name.split(".")[0],
                        imported_module=alias.name,
                        imported_name=None,
                        is_star=False,
                        is_relative=False,
                        is_top_level=is_top_level,
                    )
                )
            return
        resolved = _resolve_from_import(
            self.module_name,
            Path(self.path).name == "__init__.py",
            node,
        )
        for alias in node.names:
            self.imports.append(
                _ImportBinding(
                    path=self.path,
                    line=node.lineno,
                    bound_name=(
                        None if alias.name == "*" else alias.asname or alias.name
                    ),
                    imported_module=resolved,
                    imported_name=None if alias.name == "*" else alias.name,
                    is_star=alias.name == "*",
                    is_relative=node.level > 0,
                    is_top_level=is_top_level,
                )
            )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded_names.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name):
            self.attribute_uses.add((node.value.id, node.attr))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_dynamic_import_call(node):
            self.dynamic_import = True
        if isinstance(node.func, ast.Name) and node.func.id == "getattr" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name):
                self.dynamic_attribute_access.add(first.id)
        self.generic_visit(node)


def _resolve_from_import(
    module_name: str | None, is_initializer: bool, node: ast.ImportFrom
) -> str | None:
    if node.level == 0:
        return node.module
    if module_name is None:
        return None
    package_parts = module_name.split(".")
    if not is_initializer:
        package_parts = package_parts[:-1]
    parent_levels = node.level - 1
    if parent_levels > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - parent_levels]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


def _is_safe_top_level_statement(node: ast.stmt) -> bool:
    if isinstance(
        node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Pass
    ):
        return True
    if isinstance(node, ast.Expr):
        return isinstance(node.value, ast.Constant) and isinstance(
            node.value.value, str
        )
    if isinstance(node, ast.Assign | ast.AnnAssign):
        value = node.value
        return value is not None and _is_static_literal(value)
    return False


def _is_static_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return all(_is_static_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (key is None or _is_static_literal(key)) and _is_static_literal(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    return False


def _is_static_all_assignment(node: ast.stmt) -> bool:
    targets: list[ast.expr]
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return False
    return any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in targets
    )


def _static_all_names(node: ast.stmt) -> set[str] | None:
    value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
    if not isinstance(value, ast.List | ast.Tuple | ast.Set):
        return None
    names: set[str] = set()
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.add(element.value)
    return names


def _is_dynamic_import_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in {"__import__", "import_module"}
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
    )


@dataclass(frozen=True)
class _TargetContext:
    """Static names and attributes required to execute one test entry."""

    required_names: frozenset[str]
    attribute_uses: frozenset[tuple[str, str]]


def _parse_pytest_entry(node_id: str, profile: RepositoryProfile) -> PytestEntry:
    """Parse a conventional function or method pytest node ID.

    Parameterized node suffixes are accepted because they select the same
    function body for static import analysis.
    """
    parts = node_id.split("::")
    if len(parts) not in {2, 3} or not all(parts):
        raise ValueError(
            f"pytest node must be FILE::TEST or FILE::CLASS::TEST: {node_id}"
        )
    raw_path = Path(parts[0])
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(f"pytest node path must be repository-relative: {parts[0]}")
    path = raw_path.as_posix()
    if path not in profile.python_paths:
        raise ValueError(f"pytest node does not name a repository Python file: {path}")
    function_name = parts[-1].split("[", maxsplit=1)[0]
    class_name = parts[1] if len(parts) == 3 else None
    return PytestEntry(
        node_id=node_id,
        path=path,
        class_name=class_name,
        function_name=function_name,
    )


def _read_syntax_tree(root: Path, path: str) -> ast.Module:
    """Read one known Python source file as AST without importing it."""
    try:
        with tokenize.open(root / path) as source_file:
            return ast.parse(source_file.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        raise ValueError(
            f"target test module could not be parsed: {path}: {error}"
        ) from error


def _target_context(tree: ast.Module, entry: PytestEntry) -> _TargetContext:
    """Return names needed by a test, local helpers, fixtures, and context."""
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    target = _find_target_function(tree, entry)
    selected: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
        entry.function_name: target
    }
    pending = [target]
    required_names = _module_context_names(tree)
    attribute_uses = _module_context_attributes(tree)
    while pending:
        function = pending.pop()
        names, attributes = _node_references(function)
        required_names.update(names)
        attribute_uses.update(attributes)
        for name in names | _parameter_names(function):
            helper = functions.get(name)
            if helper is not None and name not in selected:
                selected[name] = helper
                pending.append(helper)

    target_class = _find_target_class(tree, entry.class_name)
    if target_class is not None:
        names, attributes = _class_definition_references(target_class)
        required_names.update(names)
        attribute_uses.update(attributes)
    return _TargetContext(
        required_names=frozenset(required_names),
        attribute_uses=frozenset(attribute_uses),
    )


def _find_target_function(
    tree: ast.Module, entry: PytestEntry
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Resolve the target function or direct class method named by one entry."""
    if entry.class_name is None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == entry.function_name:
                    return node
        raise ValueError(f"pytest target function was not found: {entry.node_id}")
    target_class = _find_target_class(tree, entry.class_name)
    if target_class is None:
        raise ValueError(f"pytest target class was not found: {entry.node_id}")
    for node in target_class.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == entry.function_name:
                return node
    raise ValueError(f"pytest target method was not found: {entry.node_id}")


def _find_target_class(tree: ast.Module, name: str | None) -> ast.ClassDef | None:
    """Return one direct test class, when the node ID names a class method."""
    if name is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _module_context_names(tree: ast.Module) -> set[str]:
    """Collect names needed while Python creates the target test module."""
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            continue
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        node_names, _ = _node_references(statement)
        names.update(node_names)
    return names


def _module_context_attributes(tree: ast.Module) -> set[tuple[str, str]]:
    """Collect module-level attribute accesses evaluated at import time."""
    attributes: set[tuple[str, str]] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            continue
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        _, node_attributes = _node_references(statement)
        attributes.update(node_attributes)
    return attributes


def _class_definition_references(
    node: ast.ClassDef,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Collect class-definition expressions without walking unrelated methods."""
    references: list[ast.AST] = [*node.decorator_list, *node.bases]
    references.extend(keyword.value for keyword in node.keywords)
    references.extend(
        child
        for child in node.body
        if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    names: set[str] = set()
    attributes: set[tuple[str, str]] = set()
    for reference in references:
        found_names, found_attributes = _node_references(reference)
        names.update(found_names)
        attributes.update(found_attributes)
    return names, attributes


def _node_references(node: ast.AST) -> tuple[set[str], set[tuple[str, str]]]:
    """Return loaded bare names and one-level attributes below an AST node."""
    names = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    attributes = {
        (child.value.id, child.attr)
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.ctx, ast.Load)
        and isinstance(child.value, ast.Name)
    }
    return names, attributes


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return names that may resolve to same-module pytest fixtures."""
    arguments = node.args
    return {
        argument.arg
        for argument in [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ]
    }


def _target_import_surface(
    fact: _ModuleFacts,
    context: _TargetContext,
    index: _ModuleIndex,
) -> tuple[set[tuple[str, str]], set[str]]:
    """Return target-required re-exports and packages loaded by target imports."""
    required_reexports: set[tuple[str, str]] = set()
    relevant_packages: set[str] = set()
    for binding in fact.imports:
        if not binding.is_top_level or binding.bound_name not in context.required_names:
            continue
        module = index.binding_module(binding)
        if module is None:
            continue
        parts = module.split(".")
        relevant_packages.update(
            ".".join(parts[:length]) for length in range(1, len(parts) + 1)
        )
        if binding.imported_name is not None:
            required_reexports.add(
                (binding.imported_module or module, binding.imported_name)
            )
        else:
            required_reexports.update(
                (binding.imported_module or module, attribute)
                for base, attribute in context.attribute_uses
                if base == binding.bound_name
            )
    return required_reexports, relevant_packages


def _reexport_uses(
    facts: Iterable[_ModuleFacts], index: _ModuleIndex
) -> tuple[set[tuple[str, str]], set[str], set[str]]:
    used: set[tuple[str, str]] = set()
    wildcard: set[str] = set()
    dynamic: set[str] = set()
    for fact in facts:
        for binding in fact.imports:
            module = binding.imported_module
            if module is None or index.path_for_module(module) is None:
                continue
            if binding.is_star:
                wildcard.add(module)
                continue
            if binding.imported_name is not None:
                if binding.bound_name in fact.loaded_names:
                    used.add((module, binding.imported_name))
                continue
            if binding.bound_name is None:
                continue
            consumer_module = _bound_module(binding)
            for base, attribute in fact.attribute_uses:
                if base == binding.bound_name:
                    used.add((consumer_module, attribute))
            if binding.bound_name in fact.dynamic_attribute_access:
                dynamic.add(consumer_module)
    return used, wildcard, dynamic


def _bound_module(binding: _ImportBinding) -> str:
    if binding.imported_module is None or binding.bound_name is None:
        raise ValueError("bound module requires a concrete import binding")
    if binding.bound_name == binding.imported_module.split(".")[0]:
        return binding.imported_module.split(".")[0]
    return binding.imported_module


def _discover_test_candidates(
    fact: _ModuleFacts,
    layout: RepositoryLayout,
    index: _ModuleIndex,
    facts: dict[str, _ModuleFacts],
    candidates: list[ImportCandidate],
    skips: list[ImportSkip],
    unresolved: set[str],
) -> None:
    if fact.path not in layout.test_paths:
        return
    for binding in fact.imports:
        if not binding.is_top_level:
            continue
        _consider_binding(
            "test_import", fact, binding, index, facts, candidates, skips, unresolved
        )


def _discover_reexport_candidates(
    fact: _ModuleFacts,
    index: _ModuleIndex,
    facts: dict[str, _ModuleFacts],
    used_reexports: set[tuple[str, str]],
    wildcard_reexports: set[str],
    dynamic_reexports: set[str],
    candidates: list[ImportCandidate],
    skips: list[ImportSkip],
    unresolved: set[str],
) -> None:
    if not fact.is_initializer or fact.module_name is None:
        return
    for binding in fact.imports:
        if not binding.is_top_level:
            continue
        if binding.bound_name is None:
            _consider_binding(
                "reexport", fact, binding, index, facts, candidates, skips, unresolved
            )
            continue
        if fact.dynamic_all:
            _skip(binding, skips, "dynamic_all", "package __all__ is not static")
            continue
        if binding.bound_name in fact.exported_names:
            _skip(binding, skips, "exported_via_all", "name appears in __all__")
            continue
        if (fact.module_name, binding.bound_name) in used_reexports:
            _skip(binding, skips, "reexport_used", "name has a static consumer")
            continue
        if fact.module_name in wildcard_reexports:
            _skip(binding, skips, "wildcard_consumer", "package is imported with *")
            continue
        if fact.module_name in dynamic_reexports:
            _skip(
                binding,
                skips,
                "dynamic_package_access",
                "package is used with getattr",
            )
            continue
        _consider_binding(
            "reexport", fact, binding, index, facts, candidates, skips, unresolved
        )


def _discover_target_reexport_candidates(
    fact: _ModuleFacts,
    relevant_packages: set[str],
    required_reexports: set[tuple[str, str]],
    index: _ModuleIndex,
    facts: dict[str, _ModuleFacts],
    candidates: list[ImportCandidate],
    skips: list[ImportSkip],
    unresolved: set[str],
) -> None:
    """Propose static ``__all__`` re-exports not needed by one target entry."""
    if (
        not fact.is_initializer
        or fact.module_name is None
        or fact.module_name not in relevant_packages
    ):
        return
    if fact.dynamic_all:
        for binding in fact.imports:
            if binding.is_top_level:
                _skip(binding, skips, "dynamic_all", "package __all__ is not static")
        return
    for binding in fact.imports:
        if not binding.is_top_level:
            continue
        if binding.bound_name is None:
            _skip(binding, skips, "unbound_import", "import does not bind one name")
            continue
        if binding.bound_name not in fact.exported_names:
            _skip(
                binding,
                skips,
                "not_static_reexport",
                "binding is not included in static package __all__",
            )
            continue
        if (fact.module_name, binding.bound_name) in required_reexports:
            _skip(
                binding,
                skips,
                "target_entry_used",
                "re-export is required by the target entry's import surface",
            )
            continue
        if len(fact.static_all_lines) != 1:
            _skip(
                binding,
                skips,
                "complex_all",
                "package has multiple static __all__ assignments",
            )
            continue
        _consider_binding(
            "target_reexport",
            fact,
            binding,
            index,
            facts,
            candidates,
            skips,
            unresolved,
            used_names=frozenset(),
            candidate_reason="unused_for_target_entry",
            all_line=fact.static_all_lines[0],
            allow_side_effect_risk=True,
        )


def _consider_binding(
    kind: str,
    fact: _ModuleFacts,
    binding: _ImportBinding,
    index: _ModuleIndex,
    facts: dict[str, _ModuleFacts],
    candidates: list[ImportCandidate],
    skips: list[ImportSkip],
    unresolved: set[str],
    *,
    used_names: frozenset[str] | None = None,
    candidate_reason: str = "unused_top_level_binding",
    used_skip_reason: str = "binding_used",
    used_skip_detail: str = "bound name has a static load",
    all_line: int | None = None,
    allow_side_effect_risk: bool = False,
) -> None:
    if binding.is_star:
        _skip(binding, skips, "wildcard_import", "star imports are not prunable")
        return
    if binding.bound_name is None:
        _skip(binding, skips, "unbound_import", "import does not bind one name")
        return
    if fact.dynamic_import:
        _skip(binding, skips, "dynamic_import", "module contains a dynamic import")
        return
    effective_used_names = fact.loaded_names if used_names is None else used_names
    if binding.bound_name in effective_used_names:
        _skip(binding, skips, used_skip_reason, used_skip_detail)
        return
    module = index.binding_module(binding)
    if module is None:
        _skip(binding, skips, "unresolved_relative_import", "relative base is unknown")
        return
    path = index.path_for_module(module)
    if path is None:
        if index.is_internal_prefix(module):
            unresolved.add(module)
            _skip(binding, skips, "unresolved_internal_import", module)
        else:
            _skip(binding, skips, "external_import", module)
        return
    risk_reason = None
    if not index.side_effect_free(module, facts):
        if not allow_side_effect_risk:
            _skip(binding, skips, "side_effect_risk", module)
            return
        risk_reason = "side_effect_risk"
    candidates.append(
        ImportCandidate(
            kind=kind,
            path=binding.path,
            line=binding.line,
            bound_name=binding.bound_name,
            imported_module=module,
            imported_name=binding.imported_name,
            reason=candidate_reason,
            all_line=all_line,
            risk_reason=risk_reason,
        )
    )


def _skip(
    binding: _ImportBinding, skips: list[ImportSkip], reason: str, detail: str
) -> None:
    skips.append(
        ImportSkip(
            path=binding.path,
            line=binding.line,
            bound_name=binding.bound_name,
            reason=reason,
            detail=detail,
        )
    )


def _sorted_candidates(candidates: Iterable[ImportCandidate]) -> list[ImportCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.path,
            candidate.line,
            candidate.bound_name,
            candidate.kind,
        ),
    )


def _sorted_skips(skips: Iterable[ImportSkip]) -> list[ImportSkip]:
    return sorted(
        skips,
        key=lambda skip: (
            skip.path,
            -1 if skip.line is None else skip.line,
            skip.bound_name or "",
            skip.reason,
        ),
    )
