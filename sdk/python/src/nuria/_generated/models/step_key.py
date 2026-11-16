from enum import StrEnum

class StepKey(StrEnum):
    AGENT = "agent"
    HELPER = "helper"
    MODEL = "model"
    TOOL = "tool"
    TRY = "try"

    def __str__(self) -> str:
        return str(self.value)
