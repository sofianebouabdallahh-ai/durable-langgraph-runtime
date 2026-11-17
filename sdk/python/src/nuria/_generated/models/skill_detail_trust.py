from enum import StrEnum

class SkillDetailTrust(StrEnum):
    BUILT_IN = "built_in"
    PRIVATE = "private"

    def __str__(self) -> str:
        return str(self.value)
