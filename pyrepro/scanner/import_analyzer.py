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
    """

    kind: str
    path: str
    line: int
    bound_name: str
    imported_module: str
    imported_name: str | None
    reason: str


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
            path = self.path_for_module(".".join(parts[:length]))
            if (
                path is not None
                and facts.get(path, _UNKNOWN_FACTS).top_level_side_effect_risk
            ):
                return False
        return True


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


def _consider_binding(
    kind: str,
    fact: _ModuleFacts,
    binding: _ImportBinding,
    index: _ModuleIndex,
    facts: dict[str, _ModuleFacts],
    candidates: list[ImportCandidate],
    skips: list[ImportSkip],
    unresolved: set[str],
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
    if binding.bound_name in fact.loaded_names:
        _skip(binding, skips, "binding_used", "bound name has a static load")
        return
    module = binding.imported_module
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
    if not index.side_effect_free(module, facts):
        _skip(binding, skips, "side_effect_risk", module)
        return
    candidates.append(
        ImportCandidate(
            kind=kind,
            path=binding.path,
            line=binding.line,
            bound_name=binding.bound_name,
            imported_module=module,
            imported_name=binding.imported_name,
            reason="unused_top_level_binding",
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
