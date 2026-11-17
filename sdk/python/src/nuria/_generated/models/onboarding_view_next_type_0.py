from enum import StrEnum

class OnboardingViewNextType0(StrEnum):
    AGENT = "agent"
    HELPER = "helper"
    MODEL = "model"
    TOOL = "tool"
    TRY = "try"

    def __str__(self) -> str:
        return str(self.value)
