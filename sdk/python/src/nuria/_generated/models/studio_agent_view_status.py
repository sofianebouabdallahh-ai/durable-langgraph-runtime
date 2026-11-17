from enum import StrEnum

class StudioAgentViewStatus(StrEnum):
    CHANGES = "changes"
    DRAFT = "draft"
    PUBLISHED = "published"

    def __str__(self) -> str:
        return str(self.value)
