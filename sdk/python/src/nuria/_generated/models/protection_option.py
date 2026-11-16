from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="ProtectionOption")



@_attrs_define
class ProtectionOption:
    """ 
        Attributes:
            default (bool):
            description (str):
            helpers (bool): Also applies to helpers (tool protections)
            hook (str):
            label (str):
            point (str):
     """

    default: bool
    description: str
    helpers: bool
    hook: str
    label: str
    point: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        default = self.default

        description = self.description

        helpers = self.helpers

        hook = self.hook

        label = self.label

        point = self.point


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "default": default,
            "description": description,
            "helpers": helpers,
            "hook": hook,
            "label": label,
            "point": point,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        default = d.pop("default")

        description = d.pop("description")

        helpers = d.pop("helpers")

        hook = d.pop("hook")

        label = d.pop("label")

        point = d.pop("point")

        protection_option = cls(
            default=default,
            description=description,
            helpers=helpers,
            hook=hook,
            label=label,
            point=point,
        )


        protection_option.additional_properties = d
        return protection_option

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
