from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ToolChoice")



@_attrs_define
class ToolChoice:
    """ 
        Attributes:
            name (str):
            max_calls (int | None | Unset):
     """

    name: str
    max_calls: int | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        name = self.name

        max_calls: int | None | Unset
        if isinstance(self.max_calls, Unset):
            max_calls = UNSET
        else:
            max_calls = self.max_calls


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "name": name,
        })
        if max_calls is not UNSET:
            field_dict["max_calls"] = max_calls

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        def _parse_max_calls(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_calls = _parse_max_calls(d.pop("max_calls", UNSET))


        tool_choice = cls(
            name=name,
            max_calls=max_calls,
        )

        return tool_choice

