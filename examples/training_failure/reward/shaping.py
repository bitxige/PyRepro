"""Calculate the fixture reward from tracking errors."""


def weighted_reward(errors: tuple[float, ...], weights: tuple[float, ...]) -> float:
    if len(errors) != len(weights):
        raise ValueError(
            "operands could not be broadcast together with shapes "
            f"({len(errors)},) ({len(weights)},)"
        )
    return sum(error * weight for error, weight in zip(errors, weights))
