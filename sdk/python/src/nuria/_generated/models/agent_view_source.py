from enum import StrEnum

class AgentViewSource(StrEnum):
    BUILTIN = "builtin"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
