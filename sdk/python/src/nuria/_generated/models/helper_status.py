from enum import StrEnum

class HelperStatus(StrEnum):
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    RUNNING = "running"
    TIMED_OUT = "timed_out"

    def __str__(self) -> str:
        return str(self.value)
