from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="HelperProposal")



@_attrs_define
class HelperProposal:
    """ 
        Attributes:
            description (str): What it does, in one sentence
            display_name (str): Its name, e.g. 'Flight finder'
            instructions (str): How it should do its job
            tools (list[str] | Unset): From the tools offered
     """

    description: str
    display_name: str
    instructions: str
    tools: list[str] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        description = self.description

        display_name = self.display_name

        instructions = self.instructions

        tools: list[str] | Unset = UNSET
        if not isinstance(self.tools, Unset):
            tools = self.tools




        field_dict: dict[str, Any] = {}

        field_dict.update({
            "description": description,
            "display_name": display_name,
            "instructions": instructions,
        })
        if tools is not UNSET:
            field_dict["tools"] = tools

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        description = d.pop("description")

        display_name = d.pop("display_name")

        instructions = d.pop("instructions")

        tools = cast(list[str], d.pop("tools", UNSET))


        helper_proposal = cls(
            description=description,
            display_name=display_name,
            instructions=instructions,
            tools=tools,
        )

        return helper_proposal

