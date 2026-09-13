"""Coordinate the minimal training fixture."""

from environment.road_env import sample_tracking_errors
from reward.shaping import weighted_reward


def run_training() -> float:
    errors = sample_tracking_errors()
    weights = (0.25, 0.5, 0.25)
    return weighted_reward(errors, weights)
