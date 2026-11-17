from enum import StrEnum

class NotificationViewStatus(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    PENDING = "pending"
    SENDING = "sending"
    SKIPPED = "skipped"

    def __str__(self) -> str:
        return str(self.value)
