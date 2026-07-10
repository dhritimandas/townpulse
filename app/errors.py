"""Uniform error type: every error body is {"error": ..., "hint": ...}."""


class TownPulseError(Exception):
    def __init__(self, status_code: int, error: str, hint: str) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.hint = hint
