from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
import datetime






T = TypeVar("T", bound="AdminStatus")



@_attrs_define
class AdminStatus:
    """ 
        Attributes:
            paused (bool):
            queue_depth (int): Runs waiting for a worker (R2.9)
            reason (None | str):
            updated_at (datetime.datetime):
     """

    paused: bool
    queue_depth: int
    reason: None | str
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        paused = self.paused

        queue_depth = self.queue_depth

        reason: None | str
        reason = self.reason

        updated_at = self.updated_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "paused": paused,
            "queue_depth": queue_depth,
            "reason": reason,
            "updated_at": updated_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        paused = d.pop("paused")

        queue_depth = d.pop("queue_depth")

        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))




        admin_status = cls(
            paused=paused,
            queue_depth=queue_depth,
            reason=reason,
            updated_at=updated_at,
        )


        admin_status.additional_properties = d
        return admin_status

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
