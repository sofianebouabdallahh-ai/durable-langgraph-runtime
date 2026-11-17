from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.helper_document_hooks import HelperDocumentHooks
  from ..models.helper_document_limits import HelperDocumentLimits
  from ..models.tool_choice import ToolChoice





T = TypeVar("T", bound="HelperDocument")



@_attrs_define
class HelperDocument:
    """ 
        Attributes:
            name (str):
            always_skills (list[str] | Unset):
            description (str | Unset):  Default: ''.
            display_name (None | str | Unset):
            hooks (HelperDocumentHooks | Unset):
            instructions (str | Unset):  Default: ''.
            limits (HelperDocumentLimits | Unset):
            max_turns (int | Unset):  Default: 6.
            model (str | Unset):  Default: 'chat'.
            skills (list[str] | Unset):
            temperature (float | Unset):  Default: 0.2.
            tools (list[ToolChoice] | Unset):
     """

    name: str
    always_skills: list[str] | Unset = UNSET
    description: str | Unset = ''
    display_name: None | str | Unset = UNSET
    hooks: HelperDocumentHooks | Unset = UNSET
    instructions: str | Unset = ''
    limits: HelperDocumentLimits | Unset = UNSET
    max_turns: int | Unset = 6
    model: str | Unset = 'chat'
    skills: list[str] | Unset = UNSET
    temperature: float | Unset = 0.2
    tools: list[ToolChoice] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.helper_document_hooks import HelperDocumentHooks # noqa: PLC0415
        from ..models.helper_document_limits import HelperDocumentLimits # noqa: PLC0415
        from ..models.tool_choice import ToolChoice # noqa: PLC0415
        name = self.name

        always_skills: list[str] | Unset = UNSET
        if not isinstance(self.always_skills, Unset):
            always_skills = self.always_skills



        description = self.description

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        hooks: dict[str, Any] | Unset = UNSET
        if not isinstance(self.hooks, Unset):
            hooks = self.hooks.to_dict()

        instructions = self.instructions

        limits: dict[str, Any] | Unset = UNSET
        if not isinstance(self.limits, Unset):
            limits = self.limits.to_dict()

        max_turns = self.max_turns

        model = self.model

        skills: list[str] | Unset = UNSET
        if not isinstance(self.skills, Unset):
            skills = self.skills



        temperature = self.temperature

        tools: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.tools, Unset):
            tools = []
            for tools_item_data in self.tools:
                tools_item = tools_item_data.to_dict()
                tools.append(tools_item)




        field_dict: dict[str, Any] = {}

        field_dict.update({
            "name": name,
        })
        if always_skills is not UNSET:
            field_dict["always_skills"] = always_skills
        if description is not UNSET:
            field_dict["description"] = description
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if hooks is not UNSET:
            field_dict["hooks"] = hooks
        if instructions is not UNSET:
            field_dict["instructions"] = instructions
        if limits is not UNSET:
            field_dict["limits"] = limits
        if max_turns is not UNSET:
            field_dict["max_turns"] = max_turns
        if model is not UNSET:
            field_dict["model"] = model
        if skills is not UNSET:
            field_dict["skills"] = skills
        if temperature is not UNSET:
            field_dict["temperature"] = temperature
        if tools is not UNSET:
            field_dict["tools"] = tools

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.helper_document_hooks import HelperDocumentHooks # noqa: PLC0415
        from ..models.helper_document_limits import HelperDocumentLimits # noqa: PLC0415
        from ..models.tool_choice import ToolChoice # noqa: PLC0415
        d = dict(src_dict)
        name = d.pop("name")

        always_skills = cast(list[str], d.pop("always_skills", UNSET))


        description = d.pop("description", UNSET)

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))


        _hooks = d.pop("hooks", UNSET)
        hooks: HelperDocumentHooks | Unset
        if isinstance(_hooks,  Unset):
            hooks = UNSET
        else:
            hooks = HelperDocumentHooks.from_dict(_hooks)




        instructions = d.pop("instructions", UNSET)

        _limits = d.pop("limits", UNSET)
        limits: HelperDocumentLimits | Unset
        if isinstance(_limits,  Unset):
            limits = UNSET
        else:
            limits = HelperDocumentLimits.from_dict(_limits)




        max_turns = d.pop("max_turns", UNSET)

        model = d.pop("model", UNSET)

        skills = cast(list[str], d.pop("skills", UNSET))


        temperature = d.pop("temperature", UNSET)

        _tools = d.pop("tools", UNSET)
        tools: list[ToolChoice] | Unset = UNSET
        if _tools is not UNSET:
            tools = []
            for tools_item_data in _tools:
                tools_item = ToolChoice.from_dict(tools_item_data)



                tools.append(tools_item)


        helper_document = cls(
            name=name,
            always_skills=always_skills,
            description=description,
            display_name=display_name,
            hooks=hooks,
            instructions=instructions,
            limits=limits,
            max_turns=max_turns,
            model=model,
            skills=skills,
            temperature=temperature,
            tools=tools,
        )

        return helper_document

