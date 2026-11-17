from enum import StrEnum

class AssistViewStatus(StrEnum):
    DONE = "done"
    FAILED = "failed"
    WORKING = "working"

    def __str__(self) -> str:
        return str(self.value)
