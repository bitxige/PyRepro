"""Input project for the main-guard controlled benchmark."""


def run_demo() -> None:
    """Execute the unrelated script-only behavior."""
    print("this entrypoint is not part of the strict oracle")


def trigger() -> None:
    """Raise the strict target failure."""
    raise ValueError("main guard fixture failure")


if __name__ == "__main__":
    run_demo()
