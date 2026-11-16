from enum import StrEnum

class ToolSettingsUpdateSearchProviderType0(StrEnum):
    BRAVE = "brave"
    SEARXNG = "searxng"
    TAVILY = "tavily"

    def __str__(self) -> str:
        return str(self.value)
