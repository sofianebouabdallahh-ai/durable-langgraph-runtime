from enum import StrEnum

class HelperResultStatus(StrEnum):
    FAILED = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"

    def __str__(self) -> str:
        return str(self.value)
