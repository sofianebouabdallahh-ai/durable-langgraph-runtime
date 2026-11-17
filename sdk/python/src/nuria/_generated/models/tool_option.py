from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ToolOption")



@_attrs_define
class ToolOption:
    """ 
        Attributes:
            asks_first (bool): Needs a person's approval before it runs
            description (str):
            helpers_allowed (bool): Helpers may use it (not approval-gated tools)
            label (str):
            name (str):
            risk (str):
            server (None | str | Unset): An MCP tool: its server's name (L8)
     """

    asks_first: bool
    description: str
    helpers_allowed: bool
    label: str
    name: str
    risk: str
    server: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        asks_first = self.asks_first

        description = self.description

        helpers_allowed = self.helpers_allowed

        label = self.label

        name = self.name

        risk = self.risk

        server: None | str | Unset
        if isinstance(self.server, Unset):
            server = UNSET
        else:
            server = self.server


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "asks_first": asks_first,
            "description": description,
            "helpers_allowed": helpers_allowed,
            "label": label,
            "name": name,
            "risk": risk,
        })
        if server is not UNSET:
            field_dict["server"] = server

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        asks_first = d.pop("asks_first")

        description = d.pop("description")

        helpers_allowed = d.pop("helpers_allowed")

        label = d.pop("label")

        name = d.pop("name")

        risk = d.pop("risk")

        def _parse_server(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        server = _parse_server(d.pop("server", UNSET))


        tool_option = cls(
            asks_first=asks_first,
            description=description,
            helpers_allowed=helpers_allowed,
            label=label,
            name=name,
            risk=risk,
            server=server,
        )


        tool_option.additional_properties = d
        return tool_option

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
