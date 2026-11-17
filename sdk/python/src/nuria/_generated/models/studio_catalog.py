from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.protection_option import ProtectionOption
  from ..models.studio_catalog_ceilings import StudioCatalogCeilings
  from ..models.studio_catalog_placeholders import StudioCatalogPlaceholders
  from ..models.studio_catalog_presets import StudioCatalogPresets
  from ..models.tool_option import ToolOption





T = TypeVar("T", bound="StudioCatalog")



@_attrs_define
class StudioCatalog:
    """ 
        Attributes:
            ceilings (StudioCatalogCeilings):
            placeholders (StudioCatalogPlaceholders):
            presets (StudioCatalogPresets):
            protections (list[ProtectionOption]):
            tools (list[ToolOption]):
     """

    ceilings: StudioCatalogCeilings
    placeholders: StudioCatalogPlaceholders
    presets: StudioCatalogPresets
    protections: list[ProtectionOption]
    tools: list[ToolOption]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.protection_option import ProtectionOption # noqa: PLC0415
        from ..models.studio_catalog_ceilings import StudioCatalogCeilings # noqa: PLC0415
        from ..models.studio_catalog_placeholders import StudioCatalogPlaceholders # noqa: PLC0415
        from ..models.studio_catalog_presets import StudioCatalogPresets # noqa: PLC0415
        from ..models.tool_option import ToolOption # noqa: PLC0415
        ceilings = self.ceilings.to_dict()

        placeholders = self.placeholders.to_dict()

        presets = self.presets.to_dict()

        protections = []
        for protections_item_data in self.protections:
            protections_item = protections_item_data.to_dict()
            protections.append(protections_item)



        tools = []
        for tools_item_data in self.tools:
            tools_item = tools_item_data.to_dict()
            tools.append(tools_item)




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "ceilings": ceilings,
            "placeholders": placeholders,
            "presets": presets,
            "protections": protections,
            "tools": tools,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.protection_option import ProtectionOption # noqa: PLC0415
        from ..models.studio_catalog_ceilings import StudioCatalogCeilings # noqa: PLC0415
        from ..models.studio_catalog_placeholders import StudioCatalogPlaceholders # noqa: PLC0415
        from ..models.studio_catalog_presets import StudioCatalogPresets # noqa: PLC0415
        from ..models.tool_option import ToolOption # noqa: PLC0415
        d = dict(src_dict)
        ceilings = StudioCatalogCeilings.from_dict(d.pop("ceilings"))




        placeholders = StudioCatalogPlaceholders.from_dict(d.pop("placeholders"))




        presets = StudioCatalogPresets.from_dict(d.pop("presets"))




        protections = []
        _protections = d.pop("protections")
        for protections_item_data in (_protections):
            protections_item = ProtectionOption.from_dict(protections_item_data)



            protections.append(protections_item)


        tools = []
        _tools = d.pop("tools")
        for tools_item_data in (_tools):
            tools_item = ToolOption.from_dict(tools_item_data)



            tools.append(tools_item)


        studio_catalog = cls(
            ceilings=ceilings,
            placeholders=placeholders,
            presets=presets,
            protections=protections,
            tools=tools,
        )


        studio_catalog.additional_properties = d
        return studio_catalog

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
