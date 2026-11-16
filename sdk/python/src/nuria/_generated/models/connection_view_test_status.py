from enum import StrEnum

class ConnectionViewTestStatus(StrEnum):
    FAILED = "failed"
    READY = "ready"
    UNTESTED = "untested"

    def __str__(self) -> str:
        return str(self.value)
