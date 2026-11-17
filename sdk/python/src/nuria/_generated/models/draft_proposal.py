from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.helper_proposal import HelperProposal





T = TypeVar("T", bound="DraftProposal")



@_attrs_define
class DraftProposal:
    """ 
        Attributes:
            description (str): What it's for, in one sentence
            display_name (str): The assistant's name, e.g. 'Trip planner'
            instructions (str): Its instructions, written to it ('You are…'): what it does, how it answers, what it never
                does. Placeholders allowed: {{date}}
            effort (str | Unset): quick, standard or thorough Default: 'standard'.
            helpers (list[HelperProposal] | Unset): Only if the job has clearly separate parts
            skills (list[str] | Unset): Names of skills from the library that fit
            tools (list[str] | Unset): From the tools offered
     """

    description: str
    display_name: str
    instructions: str
    effort: str | Unset = 'standard'
    helpers: list[HelperProposal] | Unset = UNSET
    skills: list[str] | Unset = UNSET
    tools: list[str] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.helper_proposal import HelperProposal # noqa: PLC0415
        description = self.description

        display_name = self.display_name

        instructions = self.instructions

        effort = self.effort

        helpers: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.helpers, Unset):
            helpers = []
            for helpers_item_data in self.helpers:
                helpers_item = helpers_item_data.to_dict()
                helpers.append(helpers_item)



        skills: list[str] | Unset = UNSET
        if not isinstance(self.skills, Unset):
            skills = self.skills



        tools: list[str] | Unset = UNSET
        if not isinstance(self.tools, Unset):
            tools = self.tools




        field_dict: dict[str, Any] = {}

        field_dict.update({
            "description": description,
            "display_name": display_name,
            "instructions": instructions,
        })
        if effort is not UNSET:
            field_dict["effort"] = effort
        if helpers is not UNSET:
            field_dict["helpers"] = helpers
        if skills is not UNSET:
            field_dict["skills"] = skills
        if tools is not UNSET:
            field_dict["tools"] = tools

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.helper_proposal import HelperProposal # noqa: PLC0415
        d = dict(src_dict)
        description = d.pop("description")

        display_name = d.pop("display_name")

        instructions = d.pop("instructions")

        effort = d.pop("effort", UNSET)

        _helpers = d.pop("helpers", UNSET)
        helpers: list[HelperProposal] | Unset = UNSET
        if _helpers is not UNSET:
            helpers = []
            for helpers_item_data in _helpers:
                helpers_item = HelperProposal.from_dict(helpers_item_data)



                helpers.append(helpers_item)


        skills = cast(list[str], d.pop("skills", UNSET))


        tools = cast(list[str], d.pop("tools", UNSET))


        draft_proposal = cls(
            description=description,
            display_name=display_name,
            instructions=instructions,
            effort=effort,
            helpers=helpers,
            skills=skills,
            tools=tools,
        )

        return draft_proposal

