from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.send_message_request_subagent_scripts_type_0_additional_property_item import SendMessageRequestSubagentScriptsType0AdditionalPropertyItem





T = TypeVar("T", bound="SendMessageRequestSubagentScriptsType0")



@_attrs_define
class SendMessageRequestSubagentScriptsType0:
    

    additional_properties: dict[str, list[SendMessageRequestSubagentScriptsType0AdditionalPropertyItem]] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.send_message_request_subagent_scripts_type_0_additional_property_item import SendMessageRequestSubagentScriptsType0AdditionalPropertyItem # noqa: PLC0415
        
        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            field_dict[prop_name] = []
            for additional_property_item_data in prop:
                additional_property_item = additional_property_item_data.to_dict()
                field_dict[prop_name].append(additional_property_item)




        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.send_message_request_subagent_scripts_type_0_additional_property_item import SendMessageRequestSubagentScriptsType0AdditionalPropertyItem # noqa: PLC0415
        d = dict(src_dict)
        send_message_request_subagent_scripts_type_0 = cls(
        )


        additional_properties = {}
        for prop_name, prop_dict in d.items():
            additional_property = []
            _additional_property = prop_dict
            for additional_property_item_data in (_additional_property):
                additional_property_item = SendMessageRequestSubagentScriptsType0AdditionalPropertyItem.from_dict(additional_property_item_data)



                additional_property.append(additional_property_item)

            additional_properties[prop_name] = additional_property

        send_message_request_subagent_scripts_type_0.additional_properties = additional_properties
        return send_message_request_subagent_scripts_type_0

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> list[SendMessageRequestSubagentScriptsType0AdditionalPropertyItem]:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: list[SendMessageRequestSubagentScriptsType0AdditionalPropertyItem]) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
