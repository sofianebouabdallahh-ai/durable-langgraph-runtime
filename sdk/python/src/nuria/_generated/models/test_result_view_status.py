from enum import StrEnum

class TestResultViewStatus(StrEnum):
    ERROR = "error"
    FAILED = "failed"
    PASSED = "passed"
    RUNNING = "running"

    def __str__(self) -> str:
        return str(self.value)
