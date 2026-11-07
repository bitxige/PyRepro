# case_if

Deterministic fixture for complete `if`-statement reduction inside a top-level
function. The false and unreachable branches are removable; the final branch
must remain because it raises the strict target failure.
