from enum import StrEnum

class RunStatus(StrEnum):
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CHILDREN = "waiting_children"

    def __str__(self) -> str:
        return str(self.value)
