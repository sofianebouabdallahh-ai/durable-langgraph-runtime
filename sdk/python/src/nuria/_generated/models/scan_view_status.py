from enum import StrEnum

class ScanViewStatus(StrEnum):
    BLOCKED = "blocked"
    CLEAN = "clean"
    REVIEW = "review"

    def __str__(self) -> str:
        return str(self.value)
