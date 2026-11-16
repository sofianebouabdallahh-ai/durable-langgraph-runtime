from enum import StrEnum

class SkillDetailOrigin(StrEnum):
    BUILT_IN = "built_in"
    CREATED = "created"
    IMPORTED = "imported"
    UPLOADED = "uploaded"

    def __str__(self) -> str:
        return str(self.value)
