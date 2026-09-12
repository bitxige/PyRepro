# Initial review specification

RepoSentinel's eventual contextual review should consider the following
dimensions. A review must follow **No Evidence, No Finding**: important claims
should name a file, symbol, and line or code region whenever possible.

## Review dimensions

- **Complexity and redundancy:** unnecessary complexity, duplicate logic,
  over-abstraction, invalid encapsulation, excessive layers, long functions,
  and mixed responsibilities.
- **Naming and code organization:** misleading or vague names, module
  responsibilities, file boundaries, placement of classes/functions, and
  coupling.
- **Public API documentation:** whether public classes and functions need
  documentation based on visibility, behavior, parameters, complexity, and
  possible exceptions. Private helpers must not be mechanically penalized.
- **Pytest quality:** behavior-focused assertions, implementation coupling,
  repetition, parameterization opportunities, setup duplication, test
  structure, and coverage of important modules.
- **Evidence-backed findings:** every important finding includes concrete code
  evidence rather than a generic quality statement.
- **Severity ranking:** findings are grouped as High, Medium, or Low Priority
  and explain the impact and recommendation.
- **Merge readiness:** the final recommendation may say Ready for merge,
  Merge after minor cleanup, Recommend cleanup before merge, or Requires
  significant refactoring, with reasons.

## Context rule

Static analysis supplies facts and candidates. The later Review Agent supplies
contextual judgement using repository exploration. Missing README, CI, or a
docstring is not automatically a quality failure.
