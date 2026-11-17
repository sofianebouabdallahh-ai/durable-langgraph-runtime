from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="SetTool")



@_attrs_define
class SetTool:
    """ 
        Attributes:
            enabled (bool):
            without_asking (bool | Unset): Only for a read-only tool Default: False.
     """

    enabled: bool
    without_asking: bool | Unset = False





    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        without_asking = self.without_asking


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "enabled": enabled,
        })
        if without_asking is not UNSET:
            field_dict["without_asking"] = without_asking

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        enabled = d.pop("enabled")

        without_asking = d.pop("without_asking", UNSET)

        set_tool = cls(
            enabled=enabled,
            without_asking=without_asking,
        )

        return set_tool

