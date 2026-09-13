# Training failure fixture

This trusted local fixture simulates a small training pipeline with a stable
reward-vector shape mismatch. The execution entry point is:

```bash
python train.py
```

The intended preserved failure is raised by
`reward/shaping.py::weighted_reward`.
