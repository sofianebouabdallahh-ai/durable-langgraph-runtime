from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.turn_status import TurnStatus
from ..models.turn_status_payload_event import TurnStatusPayloadEvent
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="TurnStatusPayload")



@_attrs_define
class TurnStatusPayload:
    """ 
        Attributes:
            event (TurnStatusPayloadEvent): The run event this status comes from
            reason (None | str): Why it failed or was cancelled, when it did
            run_id (UUID):
            status (TurnStatus): A chat turn's lifecycle on the session stream (`streaming/bus.py` TURN_STATUS_OF).
     """

    event: TurnStatusPayloadEvent
    reason: None | str
    run_id: UUID
    status: TurnStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        event = self.event.value

        reason: None | str
        reason = self.reason

        run_id = str(self.run_id)

        status = self.status.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "event": event,
            "reason": reason,
            "run_id": run_id,
            "status": status,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        event = TurnStatusPayloadEvent(d.pop("event"))




        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        run_id = UUID(d.pop("run_id"))




        status = TurnStatus(d.pop("status"))




        turn_status_payload = cls(
            event=event,
            reason=reason,
            run_id=run_id,
            status=status,
        )


        turn_status_payload.additional_properties = d
        return turn_status_payload

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
