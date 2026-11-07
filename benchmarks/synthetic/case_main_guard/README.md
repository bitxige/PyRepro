# case_main_guard

Deterministic fixture for the direct module-level `if __name__ == "__main__"`
reduction stage. The adapter imports `app`, so the guard is semantically
irrelevant to the target failure and must be removed by its dedicated stage.
