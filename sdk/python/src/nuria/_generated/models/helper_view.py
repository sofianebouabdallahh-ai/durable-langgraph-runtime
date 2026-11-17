from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.helper_view_limits import HelperViewLimits
  from ..models.helper_view_tools_item import HelperViewToolsItem





T = TypeVar("T", bound="HelperView")



@_attrs_define
class HelperView:
    """ A sub-agent (CR-005), as the UI shows it under its main agent.

        Attributes:
            description (str):
            limits (HelperViewLimits):
            max_turns (int):
            model (str):
            name (str):
            tools (list[HelperViewToolsItem]):
            prompt (None | str | Unset): GET /agents/{name} only
     """

    description: str
    limits: HelperViewLimits
    max_turns: int
    model: str
    name: str
    tools: list[HelperViewToolsItem]
    prompt: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.helper_view_limits import HelperViewLimits # noqa: PLC0415
        from ..models.helper_view_tools_item import HelperViewToolsItem # noqa: PLC0415
        description = self.description

        limits = self.limits.to_dict()

        max_turns = self.max_turns

        model = self.model

        name = self.name

        tools = []
        for tools_item_data in self.tools:
            tools_item = tools_item_data.to_dict()
            tools.append(tools_item)



        prompt: None | str | Unset
        if isinstance(self.prompt, Unset):
            prompt = UNSET
        else:
            prompt = self.prompt


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "description": description,
            "limits": limits,
            "max_turns": max_turns,
            "model": model,
            "name": name,
            "tools": tools,
        })
        if prompt is not UNSET:
            field_dict["prompt"] = prompt

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.helper_view_limits import HelperViewLimits # noqa: PLC0415
        from ..models.helper_view_tools_item import HelperViewToolsItem # noqa: PLC0415
        d = dict(src_dict)
        description = d.pop("description")

        limits = HelperViewLimits.from_dict(d.pop("limits"))




        max_turns = d.pop("max_turns")

        model = d.pop("model")

        name = d.pop("name")

        tools = []
        _tools = d.pop("tools")
        for tools_item_data in (_tools):
            tools_item = HelperViewToolsItem.from_dict(tools_item_data)



            tools.append(tools_item)


        def _parse_prompt(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        prompt = _parse_prompt(d.pop("prompt", UNSET))


        helper_view = cls(
            description=description,
            limits=limits,
            max_turns=max_turns,
            model=model,
            name=name,
            tools=tools,
            prompt=prompt,
        )


        helper_view.additional_properties = d
        return helper_view

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
