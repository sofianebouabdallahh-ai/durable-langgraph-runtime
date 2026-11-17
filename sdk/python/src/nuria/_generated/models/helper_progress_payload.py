from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID






T = TypeVar("T", bound="HelperProgressPayload")



@_attrs_define
class HelperProgressPayload:
    """ 
        Attributes:
            handle (UUID):
            message (str):
            percent (int | None):
     """

    handle: UUID
    message: str
    percent: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        handle = str(self.handle)

        message = self.message

        percent: int | None
        percent = self.percent


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "handle": handle,
            "message": message,
            "percent": percent,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        handle = UUID(d.pop("handle"))




        message = d.pop("message")

        def _parse_percent(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        percent = _parse_percent(d.pop("percent"))


        helper_progress_payload = cls(
            handle=handle,
            message=message,
            percent=percent,
        )


        helper_progress_payload.additional_properties = d
        return helper_progress_payload

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
