from enum import StrEnum

class SkillViewTrust(StrEnum):
    BUILT_IN = "built_in"
    PRIVATE = "private"

    def __str__(self) -> str:
        return str(self.value)
