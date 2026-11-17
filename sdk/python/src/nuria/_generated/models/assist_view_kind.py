from enum import StrEnum

class AssistViewKind(StrEnum):
    DRAFT = "draft"
    INSTRUCTIONS = "instructions"

    def __str__(self) -> str:
        return str(self.value)
