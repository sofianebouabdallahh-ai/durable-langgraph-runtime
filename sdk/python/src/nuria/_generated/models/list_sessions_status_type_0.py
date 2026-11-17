from enum import StrEnum

class ListSessionsStatusType0(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"

    def __str__(self) -> str:
        return str(self.value)
