# P3 symbol-failure fixture

This deterministic standard-library fixture retains four files after file-level
reduction: `reproduce.py`, `training/trainer.py`, `environment/road_env.py`,
and `reward/shaping.py`. Each retained file contains complete unused top-level
symbols. P3 must remove those symbols while preserving:

```text
ValueError: operands could not be broadcast together with shapes (4,) (3,)
reward/shaping.py::weighted_reward
```

The fixture includes a decorated top-level function and asynchronous top-level
functions to exercise AST source-span discovery.
