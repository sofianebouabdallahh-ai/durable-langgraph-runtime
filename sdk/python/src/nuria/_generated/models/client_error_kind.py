from enum import StrEnum

class ClientErrorKind(StrEnum):
    ERROR = "error"
    RENDER = "render"
    UNHANDLEDREJECTION = "unhandledrejection"

    def __str__(self) -> str:
        return str(self.value)
