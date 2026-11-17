from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.preset_limits import PresetLimits





T = TypeVar("T", bound="Preset")



@_attrs_define
class Preset:
    """ 
        Attributes:
            limits (PresetLimits):
            max_turns (int):
     """

    limits: PresetLimits
    max_turns: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.preset_limits import PresetLimits # noqa: PLC0415
        limits = self.limits.to_dict()

        max_turns = self.max_turns


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "limits": limits,
            "max_turns": max_turns,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.preset_limits import PresetLimits # noqa: PLC0415
        d = dict(src_dict)
        limits = PresetLimits.from_dict(d.pop("limits"))




        max_turns = d.pop("max_turns")

        preset = cls(
            limits=limits,
            max_turns=max_turns,
        )


        preset.additional_properties = d
        return preset

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
