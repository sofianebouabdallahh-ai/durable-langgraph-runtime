from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from uuid import UUID






T = TypeVar("T", bound="TurnAccepted")



@_attrs_define
class TurnAccepted:
    """ 
        Attributes:
            message_id (str):
            run_id (UUID):
            seq (int):
     """

    message_id: str
    run_id: UUID
    seq: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        message_id = self.message_id

        run_id = str(self.run_id)

        seq = self.seq


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "message_id": message_id,
            "run_id": run_id,
            "seq": seq,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message_id = d.pop("message_id")

        run_id = UUID(d.pop("run_id"))




        seq = d.pop("seq")

        turn_accepted = cls(
            message_id=message_id,
            run_id=run_id,
            seq=seq,
        )


        turn_accepted.additional_properties = d
        return turn_accepted

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
