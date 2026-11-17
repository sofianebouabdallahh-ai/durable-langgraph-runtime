from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
import datetime

if TYPE_CHECKING:
  from ..models.event_view_payload import EventViewPayload





T = TypeVar("T", bound="EventView")



@_attrs_define
class EventView:
    """ 
        Attributes:
            epoch (int):
            payload (EventViewPayload):
            seq (int):
            ts (datetime.datetime):
            type_ (str):
     """

    epoch: int
    payload: EventViewPayload
    seq: int
    ts: datetime.datetime
    type_: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.event_view_payload import EventViewPayload # noqa: PLC0415
        epoch = self.epoch

        payload = self.payload.to_dict()

        seq = self.seq

        ts = self.ts.isoformat()

        type_ = self.type_


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "epoch": epoch,
            "payload": payload,
            "seq": seq,
            "ts": ts,
            "type": type_,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.event_view_payload import EventViewPayload # noqa: PLC0415
        d = dict(src_dict)
        epoch = d.pop("epoch")

        payload = EventViewPayload.from_dict(d.pop("payload"))




        seq = d.pop("seq")

        ts = datetime.datetime.fromisoformat(d.pop("ts"))




        type_ = d.pop("type")

        event_view = cls(
            epoch=epoch,
            payload=payload,
            seq=seq,
            ts=ts,
            type_=type_,
        )


        event_view.additional_properties = d
        return event_view

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
