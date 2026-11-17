from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal, cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.message_view import MessageView





T = TypeVar("T", bound="MessageCreatedEvent")



@_attrs_define
class MessageCreatedEvent:
    """ A transcript message (persisted: it has a seq and is replayed).

        Attributes:
            after_seq (int | None): Transient events: the persisted seq they follow. Persisted: null
            epoch (int): The lease epoch of the worker that wrote it
            payload (MessageView):
            run_id (UUID): The run (turn) the event belongs to
            seq (int | None): Persisted events: the stream's sequence number, also sent as the SSE `id` and accepted back as
                `Last-Event-ID`. Transient events: null
            ts (datetime.datetime):
            type_ (Literal['message.created']):
     """

    after_seq: int | None
    epoch: int
    payload: MessageView
    run_id: UUID
    seq: int | None
    ts: datetime.datetime
    type_: Literal['message.created']
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.message_view import MessageView # noqa: PLC0415
        after_seq: int | None
        after_seq = self.after_seq

        epoch = self.epoch

        payload = self.payload.to_dict()

        run_id = str(self.run_id)

        seq: int | None
        seq = self.seq

        ts = self.ts.isoformat()

        type_ = self.type_


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "after_seq": after_seq,
            "epoch": epoch,
            "payload": payload,
            "run_id": run_id,
            "seq": seq,
            "ts": ts,
            "type": type_,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_view import MessageView # noqa: PLC0415
        d = dict(src_dict)
        def _parse_after_seq(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        after_seq = _parse_after_seq(d.pop("after_seq"))


        epoch = d.pop("epoch")

        payload = MessageView.from_dict(d.pop("payload"))




        run_id = UUID(d.pop("run_id"))




        def _parse_seq(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        seq = _parse_seq(d.pop("seq"))


        ts = datetime.datetime.fromisoformat(d.pop("ts"))




        type_ = cast(Literal['message.created'] , d.pop("type"))
        if type_ != 'message.created':
            raise ValueError(f"type must match const 'message.created', got '{type_}'")

        message_created_event = cls(
            after_seq=after_seq,
            epoch=epoch,
            payload=payload,
            run_id=run_id,
            seq=seq,
            ts=ts,
            type_=type_,
        )


        message_created_event.additional_properties = d
        return message_created_event

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
