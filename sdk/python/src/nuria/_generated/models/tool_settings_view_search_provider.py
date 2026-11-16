from enum import StrEnum

class ToolSettingsViewSearchProvider(StrEnum):
    BRAVE = "brave"
    SEARXNG = "searxng"
    TAVILY = "tavily"

    def __str__(self) -> str:
        return str(self.value)
