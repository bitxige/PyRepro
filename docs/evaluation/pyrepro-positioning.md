# PyRepro Positioning: Evidence, Strengths, and Limits

## Supported conclusion

PyRepro is an execution-verified reducer for trusted Python repositories. Its
workflow begins with a developer-selected argv reproduction command, protects
the original input, uses static analysis only to construct candidates, accepts
edits only after the established failure persists, and publishes output only
after an independent strict 3/3 staging check.

The completed Rich, Tactics2D, Click, attrs, and python-dateutil experiments
provide project-level evidence for that workflow. The companion
[`competitor-repository-applicability.md`](competitor-repository-applicability.md)
explains why those repository outcomes should not be conflated with
single-file tool comparisons.

## Differentiators supported by the implementation and evidence

- Repository-oriented input: Python files are reduced from a project tree,
  rather than requiring a manually extracted standalone program.
- Failure identity: the default strict oracle matches exception type,
  normalized message, and a repository-relative traceback frame; an unrelated
  import or syntax failure is rejected.
- Layered, execution-verified search: file, symbol, direct-method, complete-if,
  container/list, `__main__`-guard, and nested-list stages share one oracle and
  rollback discipline.
- Explicit cost-quality policies: Fast B applies a shared finite search budget;
  Standard with `fast-config` uses the same enabled stages to a reducer-set
  fixed point without a default search cap.
- Safe delivery boundary: only a staged 3/3-verified output is published, and
  the protected source digest is checked throughout.

## Limits that must be stated

- Greedy and bounded reductions are not globally minimal programs.
- Static facts never replace the execution oracle for acceptance.
- PyRepro runs trusted local commands in disposable copies; `shell=False` is
  not a sandbox for arbitrary untrusted repositories.
- The single-file study shows that Perses and ShrinkRay produce smaller outputs
  on the three controlled fixtures. PyRepro should not claim a universal
  statement-level minimization advantage.
- A failed or interrupted Perses project trial is an applicability result for
  this protocol and environment, not a claim about Perses in general.
- Unverified competitor capabilities are reported as “not evaluated,” not as
  unsupported.

## Presentation guidance

For a project presentation, use three separate evidence layers:

1. **Tool quality:** automated regression suite, strict Oracle handling,
   rollback, source integrity, and verified publication.
2. **Repository-scale outcomes:** Rich, Tactics2D, and the three historical
   bugs under Fast B and Standard B.
3. **External comparison:** the single-file study for fine-grained reducer
   context plus the documented Perses directory smoke and real-project NO-GO.

This framing is both stronger and more accurate than claiming that one tool
wins every reduction setting.
