from enum import StrEnum

class FileViewKind(StrEnum):
    ASSET = "asset"
    OTHER = "other"
    REFERENCE = "reference"
    SCRIPT = "script"

    def __str__(self) -> str:
        return str(self.value)
