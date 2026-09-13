# Grouped failure fixture

Run `python reproduce.py` to trigger the deterministic grouped-reduction
failure. `optional/optional_a.py` and `optional/optional_b.py` are irrelevant
to that final failure, but the loader rejects a half-present pair. Therefore,
removing either file alone changes the failure while removing both preserves it.
