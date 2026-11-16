from enum import StrEnum

class AddConnectionKind(StrEnum):
    AZURE_FOUNDRY = "azure_foundry"
    COMPATIBLE = "compatible"
    OLLAMA = "ollama"
    OPENAI = "openai"

    def __str__(self) -> str:
        return str(self.value)
