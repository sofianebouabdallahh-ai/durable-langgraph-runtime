from enum import StrEnum

class PriceViewSource(StrEnum):
    BUILT_IN = "built-in"
    CONNECTION = "connection"
    ESTIMATE = "estimate"
    LOCAL = "local"
    SETTINGS = "settings"

    def __str__(self) -> str:
        return str(self.value)
