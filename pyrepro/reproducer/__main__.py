"""Run trusted-local command-driven failure reduction as a Python module."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.budget import BudgetExhaustedError, ExecutionBudget
from pyrepro.reproducer.failure import (
    FailureMatchMode,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.import_pruner import (
    BatchImportPruner,
    format_import_pruning_summary,
)
from pyrepro.reproducer.preprocessing import (
    FixedPointPipelineReducer,
    PipelineProbeLimits,
    PipelineReductionResult,
)
from pyrepro.reproducer.probe_report import (
    validate_probe_report_path,
    write_probe_records,
)
from pyrepro.reproducer.progress import TerminalProgress
from pyrepro.reproducer.publisher import (
    FastModeTerminalState,
    PublishingResult,
    verify_and_publish,
)
from pyrepro.reproducer.reducer import (
    DdminFileReducer,
    GreedyFileReducer,
    UnstableBaselineError,
    format_reduction_summary,
)
from pyrepro.reproducer.result_report import (
    build_fast_report,
    build_standard_pipeline_report,
    build_standard_report,
    validate_report_paths,
    write_reports,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.symbol_reducer import (
    GreedySymbolReducer,
    SymbolOrder,
    format_symbol_reduction_summary,
)
from pyrepro.reproducer.workspace import ReductionWorkspace
from pyrepro.scanner.import_analyzer import (
    ImportAnalyzer,
    format_import_analysis,
    format_target_import_analysis,
)

_DEFAULT_OUTPUT_DIRECTORY_NAME = ".pyrepro-output"
_FAST_DEFAULT_STAGE_LIMITS = PipelineProbeLimits(
    import_pruning=16,
    coarse=16,
    symbol=60,
    method=265,
    if_statement=60,
    container_entry=60,
    list_entry=60,
    main_guard=8,
    nested_list_entry=12,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Reduce a trusted local project while preserving a stable Python failure.

    Args:
        argv: Optional command-line arguments excluding the executable name.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(
        description="Reduce a trusted local Python project while preserving a failure."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    reduce_parser = subparsers.add_parser(
        "reduce", help="reduce one trusted local project"
    )
    analyze_parser = subparsers.add_parser(
        "analyze-imports",
        help="inspect Python import-pruning candidates without execution",
    )
    prune_parser = subparsers.add_parser(
        "prune-imports",
        help="execution-verify bounded batches of target-aware import edits",
    )
    analyze_parser.add_argument("source", type=Path, help="local project root")
    analyze_parser.add_argument(
        "--pytest-node",
        help=(
            "scope candidates to FILE::TEST or FILE::CLASS::TEST without "
            "executing the test"
        ),
    )
    reduce_parser.add_argument("source", type=Path, help="trusted local project root")
    _configure_prune_parser(prune_parser)
    reduce_parser.add_argument(
        "--output",
        type=Path,
        help="new reduced-project directory (default: sibling .pyrepro-output/<name>)",
    )
    reduce_parser.add_argument(
        "--timeout-seconds",
        default=5.0,
        type=float,
        help="maximum duration for each command execution (default: 5)",
    )
    reduce_parser.add_argument(
        "--expect",
        help="text that must occur in the stable baseline failure signature",
    )
    reduce_parser.add_argument(
        "--failure-match",
        choices=tuple(mode.value for mode in FailureMatchMode),
        default=FailureMatchMode.STRICT.value,
        help=(
            "failure identity for reduction; strict is the product default, "
            "message is for controlled comparisons"
        ),
    )
    reduce_parser.add_argument(
        "--strategy",
        choices=("greedy", "ddmin"),
        default="greedy",
        help="file-reduction strategy (default: greedy)",
    )
    reduce_parser.add_argument(
        "--max-granularity",
        choices=("file", "symbol"),
        default="file",
        help="stop after file reduction or continue with symbols (default: file)",
    )
    reduce_parser.add_argument(
        "--mode",
        choices=("standard", "fast"),
        default="standard",
        help="reduction mode; fast uses a shared execution budget (default: standard)",
    )
    reduce_parser.add_argument(
        "--progress",
        choices=("auto", "on", "off"),
        default="auto",
        help=(
            "terminal reduction progress: auto uses an interactive terminal, "
            "on forces it, off disables it (default: auto)"
        ),
    )
    reduce_parser.add_argument(
        "--pytest-node",
        help=(
            "target test node required by --mode fast and used by Standard "
            "Mode's unified pipeline as FILE::TEST or FILE::CLASS::TEST"
        ),
    )
    reduce_parser.add_argument(
        "--standard-stage-policy",
        choices=("full", "fast-config"),
        default="full",
        help=(
            "Standard Mode stage enablement: full enables every production "
            "stage; fast-config mirrors zero/nonzero --max-*-probes settings "
            "while leaving enabled stages unbounded (default: full)"
        ),
    )
    reduce_parser.add_argument(
        "--max-oracle-executions",
        type=int,
        help=(
            "optional global Oracle-command limit; required by --mode fast (minimum: 6)"
        ),
    )
    reduce_parser.add_argument(
        "--max-time-seconds",
        type=float,
        help="optional shared wall-clock deadline for target-aware reduction",
    )
    reduce_parser.add_argument(
        "--max-import-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.import_pruning,
        help="bounded import-pruning probes for --mode fast (default: 16)",
    )
    reduce_parser.add_argument(
        "--max-coarse-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.coarse,
        help="bounded coarse file probes for --mode fast (default: 16; zero disables)",
    )
    reduce_parser.add_argument(
        "--max-symbol-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.symbol,
        help=(
            "bounded complete-symbol probes after Fast Mode file cleanup "
            "(default: 60; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-method-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.method,
        help=(
            "bounded direct-class-method probes after Fast Mode symbol cleanup "
            "(default: 265; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-if-statement-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.if_statement,
        help=(
            "experimental bounded complete-if probes after Fast Mode method cleanup "
            "(default: 60; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-container-entry-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.container_entry,
        help=(
            "experimental bounded module-dictionary entry probes after Fast Mode "
            "complete-if cleanup (default: 60; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-list-entry-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.list_entry,
        help=(
            "experimental bounded module-list entry probes after Fast Mode "
            "container-entry cleanup (default: 60; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-main-guard-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.main_guard,
        help=(
            "experimental bounded module-level __main__ guard probes after Fast "
            "Mode list-entry cleanup (default: 8; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--max-nested-list-entry-probes",
        type=int,
        default=_FAST_DEFAULT_STAGE_LIMITS.nested_list_entry,
        help=(
            "experimental bounded nested Palette RGB-list entry probes after Fast "
            "Mode main-guard cleanup (default: 12; zero disables)"
        ),
    )
    reduce_parser.add_argument(
        "--symbol-order",
        choices=tuple(order.value for order in SymbolOrder),
        default=SymbolOrder.DISCOVERY.value,
        help=(
            "candidate order for enabled Fast Mode symbol probes (default: discovery)"
        ),
    )
    reduce_parser.add_argument(
        "--probe-records",
        type=Path,
        help=(
            "write optional file-reduction probe telemetry as new JSONL outside "
            "the source project"
        ),
    )
    reduce_parser.add_argument(
        "--json-report",
        type=Path,
        help="write an optional final JSON result report outside the source project",
    )
    reduce_parser.add_argument(
        "--html-report",
        type=Path,
        help="write an optional final HTML result report outside the source project",
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "analyze-imports":
        return _analyze_imports(parser, arguments)
    if "-h" in arguments or "--help" in arguments:
        parser.parse_args(arguments)
    try:
        command_separator = arguments.index("--")
    except ValueError:
        parser.error("a reproduction command is required after --")
    command = arguments[command_separator + 1 :]
    if not command:
        parser.error("a reproduction command is required after --")
    args = parser.parse_args(arguments[:command_separator])
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source root is not a directory: {source}")
    output = args.output or _default_output_directory(source)
    json_report: Path | None = None
    html_report: Path | None = None
    try:
        probe_report = (
            None
            if args.probe_records is None
            else validate_probe_report_path(args.probe_records, source)
        )
        if args.operation == "reduce":
            json_report, html_report = validate_report_paths(
                args.json_report, args.html_report, source, output
            )
            if probe_report is not None and probe_report in {json_report, html_report}:
                raise ValueError(
                    "probe report and final report paths must be different"
                )
    except ValueError as error:
        parser.error(str(error))

    if args.operation == "prune-imports":
        return _prune_imports(
            parser,
            args,
            source,
            output,
            probe_report,
            command,
        )
    print("Warning: PyRepro will repeatedly execute the supplied command.", flush=True)
    print("Only run a project and command that you trust.", flush=True)
    if args.mode == "fast":
        return _reduce_fast(
            parser,
            args,
            source,
            output,
            probe_report,
            json_report,
            html_report,
            command,
        )
    if args.strategy == "greedy" and args.pytest_node is not None:
        return _reduce_standard_pipeline(
            parser,
            args,
            source,
            output,
            probe_report,
            json_report,
            html_report,
            command,
        )
    started_at = perf_counter()
    try:
        with TerminalProgress(args.progress) as progress:
            runner = CommandRunner(
                command,
                timeout_seconds=args.timeout_seconds,
                on_execution_start=progress.advance,
            )
            reducer_type = (
                GreedyFileReducer if args.strategy == "greedy" else DdminFileReducer
            )
            match_mode = FailureMatchMode(args.failure_match)
            reducer = reducer_type(
                runner,
                expected_text=args.expect,
                match_mode=match_mode,
            )
            with ReductionWorkspace(source) as workspace:
                file_result = reducer.reduce(workspace)
                symbol_result = None
                if args.max_granularity == "symbol":
                    symbol_result = GreedySymbolReducer(
                        runner, match_mode=match_mode
                    ).reduce(workspace, file_result.baseline_signature)
                destination = workspace.copy_reduced_to(output)
                output_result = runner.run(destination)
                output_outcome = classify_result(
                    output_result,
                    file_result.baseline_signature,
                    destination,
                    match_mode,
                )
    except BudgetExhaustedError as error:
        parser.error(f"Standard Mode stopped before verification: {error}")
    except (OSError, UnstableBaselineError, ValueError) as error:
        parser.error(str(error))

    if output_outcome is not ReductionOutcome.SAME_FAILURE:
        parser.error("copied reduced project did not reproduce the baseline failure")

    if probe_report is not None:
        try:
            write_probe_records(probe_report, file_result)
        except OSError as error:
            parser.error(
                "failed to write probe records; the verified reduced project "
                f"remains at {destination}: {error}"
            )

    if json_report is not None or html_report is not None:
        try:
            write_reports(
                build_standard_report(
                    source,
                    destination,
                    file_result,
                    symbol_result,
                    run_wall_clock_seconds=perf_counter() - started_at,
                ),
                json_report,
                html_report,
            )
        except OSError as error:
            parser.error(
                "failed to write final result report; the verified reduced project "
                f"remains at {destination}: {error}"
            )

    print(format_reduction_summary(file_result))
    if symbol_result is not None:
        print()
        print(format_symbol_reduction_summary(symbol_result))
        print(
            "Total oracle executions: "
            f"{file_result.executions + symbol_result.executions}"
        )
        print(
            "Total wall-clock seconds: "
            f"{file_result.wall_clock_seconds + symbol_result.wall_clock_seconds:.3f}"
        )
    print(f"Reduced project: {destination}")
    if probe_report is not None:
        print(f"Probe records: {probe_report}")
    if json_report is not None:
        print(f"JSON report: {json_report}")
    if html_report is not None:
        print(f"HTML report: {html_report}")
    return 0


def _reduce_standard_pipeline(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    source: Path,
    output: Path,
    probe_report: Path | None,
    json_report: Path | None,
    html_report: Path | None,
    command: Sequence[str],
) -> int:
    """Run the complete reducer lineup without Fast Mode's shared budget.

    A supplied pytest node opts Standard Mode into the same ordered, target-aware
    stages as Fast Mode.  The reducers receive no per-stage or global probe
    bounds; the three-run final verification remains strict.
    """
    started_at = perf_counter()
    try:
        match_mode = FailureMatchMode(args.failure_match)
        budget = (
            None
            if args.max_oracle_executions is None and args.max_time_seconds is None
            else ExecutionBudget(
                args.max_oracle_executions,
                time_budget_seconds=args.max_time_seconds,
            )
        )
        with TerminalProgress(args.progress) as progress:
            runner = CommandRunner(
                command,
                timeout_seconds=args.timeout_seconds,
                on_execution_start=progress.advance,
            )
            reducer = FixedPointPipelineReducer(
                runner,
                args.pytest_node,
                expected_text=args.expect,
                match_mode=match_mode,
                limits=_standard_pipeline_limits(args),
                symbol_order=SymbolOrder(args.symbol_order),
            )
            with ReductionWorkspace(source) as workspace:
                reduction = reducer.reduce(workspace, budget=budget)
                if not reduction.source_unchanged:
                    raise UnstableBaselineError("the protected source changed")
                publication = verify_and_publish(
                    workspace,
                    runner,
                    reduction.baseline_signature,
                    match_mode,
                    output,
                    budget,
                    search_budget_exhausted=reduction.budget_exhausted,
                )
    except (OSError, UnstableBaselineError, ValueError) as error:
        parser.error(str(error))

    if not publication.verified or publication.output_path is None:
        parser.error(_fast_state_message(publication))
    destination = publication.output_path

    if probe_report is not None:
        try:
            write_probe_records(probe_report, reduction)
        except OSError as error:
            parser.error(
                "failed to write probe records; the verified reduced project "
                f"remains at {destination}: {error}"
            )

    report = build_standard_pipeline_report(
        source,
        reduction,
        publication,
        run_wall_clock_seconds=perf_counter() - started_at,
    )
    if json_report is not None or html_report is not None:
        try:
            write_reports(report, json_report, html_report)
        except OSError as error:
            parser.error(
                "failed to write final result report; the verified reduced project "
                f"remains at {destination}: {error}"
            )

    if reduction.budget_exhausted:
        print(
            "Standard Mode stopped reduction at the explicit search limit, "
            "then published its final 3/3-verified candidate."
        )
    else:
        print("Standard Mode completed successfully.")
    print(_standard_pipeline_status(reduction, budget))
    print("Final verification: 3/3 passed")
    print(f"Reducer Oracle executions: {reduction.executions}")
    print(f"Total Oracle executions: {report['oracle']['total_executions']}")
    print(f"Total wall-clock seconds: {report['timing']['run_wall_clock_seconds']:.3f}")
    print(f"Reduced project: {destination}")
    if probe_report is not None:
        print(f"Probe records: {probe_report}")
    if json_report is not None:
        print(f"JSON report: {json_report}")
    if html_report is not None:
        print(f"HTML report: {html_report}")
    return 0


def _reduce_fast(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    source: Path,
    output: Path,
    probe_report: Path | None,
    json_report: Path | None,
    html_report: Path | None,
    command: Sequence[str],
) -> int:
    """Run the existing budgeted pipeline and report its publishing state.

    This function deliberately orchestrates existing components only. Publisher
    destination and source-integrity rules remain owned by
    :func:`verify_and_publish`.
    """
    _validate_fast_arguments(parser, args)
    started_at = perf_counter()
    try:
        match_mode = FailureMatchMode(args.failure_match)
        budget = ExecutionBudget(
            args.max_oracle_executions,
            time_budget_seconds=args.max_time_seconds,
        )
        with TerminalProgress(
            args.progress, total_executions=args.max_oracle_executions
        ) as progress:
            runner = CommandRunner(
                command,
                timeout_seconds=args.timeout_seconds,
                on_execution_start=progress.advance,
            )
            reducer = FixedPointPipelineReducer(
                runner,
                args.pytest_node,
                expected_text=args.expect,
                match_mode=match_mode,
                limits=_fast_pipeline_limits(args),
                symbol_order=SymbolOrder(args.symbol_order),
            )
            with ReductionWorkspace(source) as workspace:
                reduction = reducer.reduce(workspace, budget=budget)
                publication = verify_and_publish(
                    workspace,
                    runner,
                    reduction.baseline_signature,
                    match_mode,
                    output,
                    budget,
                    search_budget_exhausted=reduction.budget_exhausted,
                )
                report = build_fast_report(
                    source,
                    workspace.root,
                    reduction,
                    publication,
                    run_wall_clock_seconds=perf_counter() - started_at,
                )
    except UnstableBaselineError as error:
        _print_fast_failure("baseline_failed", str(error))
        return 1
    except BudgetExhaustedError as error:
        _print_fast_failure("budget_exhausted_unverified", str(error))
        return 1
    except (OSError, ValueError) as error:
        _print_fast_failure("runtime_error", str(error))
        return 1

    probe_report_written = False
    if probe_report is not None:
        try:
            write_probe_records(probe_report, reduction)
            probe_report_written = True
        except OSError as error:
            print(f"Warning: failed to write probe records: {error}", file=sys.stderr)

    report_written = True
    if json_report is not None or html_report is not None:
        try:
            write_reports(report, json_report, html_report)
        except OSError as error:
            report_written = False
            print(
                f"Warning: failed to write final result report: {error}",
                file=sys.stderr,
            )

    _print_fast_publication(publication, reduction)
    if probe_report_written:
        print(f"Probe records: {probe_report}")
    if json_report is not None and report_written:
        print(f"JSON report: {json_report}")
    if html_report is not None and report_written:
        print(f"HTML report: {html_report}")
    return 0 if publication.verified and report_written else 1


def _fast_pipeline_limits(args: argparse.Namespace) -> PipelineProbeLimits:
    """Return Fast Mode's explicit, bounded stage policy."""
    return PipelineProbeLimits(
        import_pruning=args.max_import_probes,
        coarse=args.max_coarse_probes,
        symbol=args.max_symbol_probes,
        method=args.max_method_probes,
        if_statement=args.max_if_statement_probes,
        container_entry=args.max_container_entry_probes,
        list_entry=args.max_list_entry_probes,
        main_guard=args.max_main_guard_probes,
        nested_list_entry=args.max_nested_list_entry_probes,
    )


def _standard_pipeline_limits(args: argparse.Namespace) -> PipelineProbeLimits:
    """Return Standard's full or Fast-config-matched unbounded stage policy."""
    if args.standard_stage_policy == "full":
        return PipelineProbeLimits(
            import_pruning=None,
            coarse=None,
            symbol=None,
            method=None,
            if_statement=None,
            container_entry=None,
            list_entry=None,
            main_guard=None,
            nested_list_entry=None,
        )
    fast_limits = _fast_pipeline_limits(args)
    return PipelineProbeLimits(
        **{name: None if value > 0 else 0 for name, value in vars(fast_limits).items()}
    )


def _standard_pipeline_status(
    reduction: PipelineReductionResult,
    budget: ExecutionBudget | None,
) -> str:
    """Describe Standard's actual search policy and termination truthfully."""
    if reduction.budget_exhausted:
        return "Pipeline: explicit Standard search budget exhausted."
    if budget is None:
        return "Pipeline: unbounded search with the Fast Mode reducer lineup."
    return "Pipeline: explicit Standard search budget completed at a fixed point."


def _validate_fast_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Reject options that Fast Mode cannot faithfully honor."""
    if args.pytest_node is None:
        parser.error("--pytest-node is required with --mode fast")
    if args.max_oracle_executions is None:
        parser.error("--max-oracle-executions is required with --mode fast")
    if args.strategy != "greedy":
        parser.error("--mode fast supports only --strategy greedy")
    if args.max_granularity != "file":
        parser.error("--mode fast supports only --max-granularity file")
    if args.max_import_probes <= 0:
        parser.error("--max-import-probes must be positive with --mode fast")
    if args.max_coarse_probes < 0:
        parser.error("--max-coarse-probes must not be negative with --mode fast")
    if args.max_symbol_probes < 0:
        parser.error("--max-symbol-probes must not be negative with --mode fast")
    if args.max_method_probes < 0:
        parser.error("--max-method-probes must not be negative with --mode fast")
    if args.max_if_statement_probes < 0:
        parser.error("--max-if-statement-probes must not be negative with --mode fast")
    if args.max_container_entry_probes < 0:
        parser.error(
            "--max-container-entry-probes must not be negative with --mode fast"
        )
    if args.max_list_entry_probes < 0:
        parser.error("--max-list-entry-probes must not be negative with --mode fast")
    if args.max_main_guard_probes < 0:
        parser.error("--max-main-guard-probes must not be negative with --mode fast")
    if args.max_nested_list_entry_probes < 0:
        parser.error(
            "--max-nested-list-entry-probes must not be negative with --mode fast"
        )
    if (
        args.max_symbol_probes == 0
        and args.max_method_probes == 0
        and args.symbol_order != SymbolOrder.DISCOVERY.value
    ):
        parser.error(
            "--symbol-order requires --max-symbol-probes or "
            "--max-method-probes greater than zero"
        )


def _print_fast_publication(
    publication: PublishingResult,
    reduction: PipelineReductionResult,
) -> None:
    """Print one clear result without changing publisher terminal semantics."""
    if publication.state is FastModeTerminalState.COMPLETED:
        print("Fast Mode completed successfully.")
        print(f"Published reproducer: {publication.output_path}")
        print("Final verification: 3/3 passed")
    elif publication.state is FastModeTerminalState.BUDGET_EXHAUSTED_VERIFIED:
        print(
            "Fast Mode stopped reduction because the search budget was exhausted, "
            "but the accepted candidate passed final 3/3 verification and was "
            "published."
        )
        print(f"Published reproducer: {publication.output_path}")
        print("Final verification: 3/3 passed")
    else:
        print(f"Fast Mode failed: {_fast_state_message(publication)}")
        print("No official reproducer was published.")
    print(f"Reducer Oracle executions: {reduction.executions}")
    print(f"Total Oracle executions: {publication.budget.executions_started}")
    print(f"Search probes: {len(reduction.probe_records)}")
    symbol_result = _aggregate_pipeline_stage(reduction, "symbol_reduction")
    if symbol_result is not None:
        print(
            "Symbol probes: "
            f"{symbol_result['candidate_attempts']} "
            f"({symbol_result['accepted_removals']} accepted)"
        )
    method_result = _aggregate_pipeline_stage(reduction, "method_reduction")
    if method_result is not None:
        print(
            "Method probes: "
            f"{method_result['candidate_attempts']} "
            f"({method_result['accepted_removals']} accepted)"
        )
    if_result = _aggregate_pipeline_stage(reduction, "if_statement_reduction")
    if if_result is not None:
        print(
            "If-statement probes: "
            f"{if_result['candidate_attempts']} "
            f"({if_result['accepted_removals']} accepted)"
        )
    container_result = _aggregate_pipeline_stage(reduction, "container_entry_reduction")
    if container_result is not None:
        print(
            "Container-entry probes: "
            f"{container_result['candidate_attempts']} "
            f"({container_result['accepted_batches']} accepted)"
        )
        print(f"Container entries removed: {container_result['removed_entries']}")
    list_result = _aggregate_pipeline_stage(reduction, "list_entry_reduction")
    if list_result is not None:
        print(
            "List-entry probes: "
            f"{list_result['candidate_attempts']} "
            f"({list_result['accepted_batches']} accepted)"
        )
        print(f"List entries removed: {list_result['removed_entries']}")
    main_guard_result = _aggregate_pipeline_stage(reduction, "main_guard_reduction")
    if main_guard_result is not None:
        print(
            "Main-guard probes: "
            f"{main_guard_result['candidate_attempts']} "
            f"({main_guard_result['accepted_batches']} accepted)"
        )
        print(f"Main guards removed: {main_guard_result['removed_guards']}")
    nested_result = _aggregate_pipeline_stage(reduction, "nested_list_entry_reduction")
    if nested_result is not None:
        print(
            "Nested-list-entry probes: "
            f"{nested_result['candidate_attempts']} "
            f"({nested_result['accepted_batches']} accepted)"
        )
        print(f"Nested list entries removed: {nested_result['removed_entries']}")


def _aggregate_pipeline_stage(
    reduction: PipelineReductionResult,
    attribute: str,
) -> dict[str, int] | None:
    """Aggregate printable stage counters over all fixed-point sweeps."""
    matching = [
        stage
        for sweep in reduction.sweeps
        if (stage := getattr(sweep, attribute)) is not None
    ]
    if not matching:
        return None
    counter_names = (
        "candidate_attempts",
        "accepted_removals",
        "accepted_batches",
        "removed_entries",
        "removed_guards",
    )
    return {
        name: sum(int(getattr(stage, name, 0)) for stage in matching)
        for name in counter_names
    }


def _fast_state_message(publication: PublishingResult) -> str:
    """Return a user-facing explanation for one existing publisher state."""
    messages = {
        FastModeTerminalState.BUDGET_EXHAUSTED_UNVERIFIED: (
            "the budget ended before final 3/3 verification completed"
        ),
        FastModeTerminalState.FINAL_VERIFICATION_FAILED: (
            "final verification did not reproduce the baseline failure"
        ),
        FastModeTerminalState.BASELINE_FAILED: "the baseline could not be established",
        FastModeTerminalState.SOURCE_CHANGED: "the protected source changed",
        FastModeTerminalState.RUNTIME_ERROR: "a runtime or publication error occurred",
    }
    detail = messages.get(publication.state, publication.state.value)
    if publication.error_message:
        return f"{detail}: {publication.error_message}"
    return detail


def _print_fast_failure(state: str, detail: str) -> None:
    """Report a pipeline failure that occurred before publisher dispatch."""
    print(f"Fast Mode failed: {state}: {detail}", file=sys.stderr)
    print("No official reproducer was published.", file=sys.stderr)


def _configure_prune_parser(parser: argparse.ArgumentParser) -> None:
    """Add the intentionally narrow PR5.2c import-pruning CLI arguments."""
    parser.add_argument("source", type=Path, help="trusted local project root")
    parser.add_argument(
        "--pytest-node",
        required=True,
        help="target test node as FILE::TEST or FILE::CLASS::TEST",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="new pruned-project directory (default: sibling .pyrepro-output/<name>)",
    )
    parser.add_argument(
        "--timeout-seconds",
        default=5.0,
        type=float,
        help="maximum duration for each command execution (default: 5)",
    )
    parser.add_argument(
        "--expect",
        help="text that must occur in the stable baseline failure signature",
    )
    parser.add_argument(
        "--failure-match",
        choices=tuple(mode.value for mode in FailureMatchMode),
        default=FailureMatchMode.STRICT.value,
        help="failure identity for pruning; strict is the product default",
    )
    parser.add_argument(
        "--max-import-probes",
        type=int,
        default=16,
        help="maximum bounded import-pruning probes (default: 16)",
    )
    parser.add_argument(
        "--probe-records",
        type=Path,
        help="write optional import-pruning JSONL telemetry outside the source project",
    )


def _prune_imports(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    source: Path,
    output: Path,
    probe_report: Path | None,
    command: Sequence[str],
) -> int:
    """Execute bounded target-aware import pruning in a disposable workspace."""
    print("Warning: PyRepro will repeatedly execute the supplied command.")
    print("Only run a project and command that you trust.")
    try:
        runner = CommandRunner(command, timeout_seconds=args.timeout_seconds)
        match_mode = FailureMatchMode(args.failure_match)
        pruner = BatchImportPruner(
            runner,
            args.pytest_node,
            expected_text=args.expect,
            match_mode=match_mode,
            max_probes=args.max_import_probes,
        )
        with ReductionWorkspace(source) as workspace:
            result = pruner.prune(workspace)
            destination = workspace.copy_reduced_to(output)
            output_result = runner.run(destination)
            output_outcome = classify_result(
                output_result,
                result.baseline_signature,
                destination,
                match_mode,
            )
    except (OSError, UnstableBaselineError, ValueError) as error:
        parser.error(str(error))

    if output_outcome is not ReductionOutcome.SAME_FAILURE:
        parser.error("copied pruned project did not reproduce the baseline failure")
    if probe_report is not None:
        try:
            write_probe_records(probe_report, result)
        except OSError as error:
            parser.error(
                "failed to write probe records; the verified pruned project "
                f"remains at {destination}: {error}"
            )
    print(format_import_pruning_summary(result))
    print(f"Pruned project: {destination}")
    if probe_report is not None:
        print(f"Probe records: {probe_report}")
    return 0


def _analyze_imports(parser: argparse.ArgumentParser, arguments: Sequence[str]) -> int:
    """Run static import analysis without running a reproduction command."""
    args = parser.parse_args(arguments)
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source root is not a directory: {source}")
    try:
        analyzer = ImportAnalyzer(source)
        analysis = (
            analyzer.analyze()
            if args.pytest_node is None
            else analyzer.analyze_pytest_node(args.pytest_node)
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    formatter = (
        format_import_analysis
        if args.pytest_node is None
        else format_target_import_analysis
    )
    print(formatter(analysis))
    return 0


def _default_output_directory(source: Path) -> Path:
    """Return a sibling output path that cannot be inside source by default."""
    return source.parent / _DEFAULT_OUTPUT_DIRECTORY_NAME / source.name


if __name__ == "__main__":
    raise SystemExit(main())
