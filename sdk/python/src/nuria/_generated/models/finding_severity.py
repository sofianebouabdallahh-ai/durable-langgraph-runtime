from enum import StrEnum

class FindingSeverity(StrEnum):
    BLOCK = "block"
    REVIEW = "review"

    def __str__(self) -> str:
        return str(self.value)
