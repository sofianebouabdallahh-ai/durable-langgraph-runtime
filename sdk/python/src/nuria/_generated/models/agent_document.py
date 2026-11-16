from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.agent_document_hooks import AgentDocumentHooks
  from ..models.agent_document_limits import AgentDocumentLimits
  from ..models.helper_document import HelperDocument
  from ..models.tool_choice import ToolChoice





T = TypeVar("T", bound="AgentDocument")



@_attrs_define
class AgentDocument:
    """ 
        Attributes:
            name (str):
            always_skills (list[str] | Unset):
            description (str | Unset):  Default: ''.
            display_name (None | str | Unset):
            helpers (list[HelperDocument] | Unset):
            hooks (AgentDocumentHooks | Unset):
            instructions (str | Unset):  Default: ''.
            limits (AgentDocumentLimits | Unset):
            max_session_turns (int | None | Unset):
            max_turns (int | Unset):  Default: 20.
            model (str | Unset):  Default: 'chat'.
            skills (list[str] | Unset):
            temperature (float | Unset):  Default: 0.2.
            tools (list[ToolChoice] | Unset):
     """

    name: str
    always_skills: list[str] | Unset = UNSET
    description: str | Unset = ''
    display_name: None | str | Unset = UNSET
    helpers: list[HelperDocument] | Unset = UNSET
    hooks: AgentDocumentHooks | Unset = UNSET
    instructions: str | Unset = ''
    limits: AgentDocumentLimits | Unset = UNSET
    max_session_turns: int | None | Unset = UNSET
    max_turns: int | Unset = 20
    model: str | Unset = 'chat'
    skills: list[str] | Unset = UNSET
    temperature: float | Unset = 0.2
    tools: list[ToolChoice] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_document_hooks import AgentDocumentHooks # noqa: PLC0415
        from ..models.agent_document_limits import AgentDocumentLimits # noqa: PLC0415
        from ..models.helper_document import HelperDocument # noqa: PLC0415
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

        helpers: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.helpers, Unset):
            helpers = []
            for helpers_item_data in self.helpers:
                helpers_item = helpers_item_data.to_dict()
                helpers.append(helpers_item)



        hooks: dict[str, Any] | Unset = UNSET
        if not isinstance(self.hooks, Unset):
            hooks = self.hooks.to_dict()

        instructions = self.instructions

        limits: dict[str, Any] | Unset = UNSET
        if not isinstance(self.limits, Unset):
            limits = self.limits.to_dict()

        max_session_turns: int | None | Unset
        if isinstance(self.max_session_turns, Unset):
            max_session_turns = UNSET
        else:
            max_session_turns = self.max_session_turns

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
        if helpers is not UNSET:
            field_dict["helpers"] = helpers
        if hooks is not UNSET:
            field_dict["hooks"] = hooks
        if instructions is not UNSET:
            field_dict["instructions"] = instructions
        if limits is not UNSET:
            field_dict["limits"] = limits
        if max_session_turns is not UNSET:
            field_dict["max_session_turns"] = max_session_turns
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
        from ..models.agent_document_hooks import AgentDocumentHooks # noqa: PLC0415
        from ..models.agent_document_limits import AgentDocumentLimits # noqa: PLC0415
        from ..models.helper_document import HelperDocument # noqa: PLC0415
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


        _helpers = d.pop("helpers", UNSET)
        helpers: list[HelperDocument] | Unset = UNSET
        if _helpers is not UNSET:
            helpers = []
            for helpers_item_data in _helpers:
                helpers_item = HelperDocument.from_dict(helpers_item_data)



                helpers.append(helpers_item)


        _hooks = d.pop("hooks", UNSET)
        hooks: AgentDocumentHooks | Unset
        if isinstance(_hooks,  Unset):
            hooks = UNSET
        else:
            hooks = AgentDocumentHooks.from_dict(_hooks)




        instructions = d.pop("instructions", UNSET)

        _limits = d.pop("limits", UNSET)
        limits: AgentDocumentLimits | Unset
        if isinstance(_limits,  Unset):
            limits = UNSET
        else:
            limits = AgentDocumentLimits.from_dict(_limits)




        def _parse_max_session_turns(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_session_turns = _parse_max_session_turns(d.pop("max_session_turns", UNSET))


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


        agent_document = cls(
            name=name,
            always_skills=always_skills,
            description=description,
            display_name=display_name,
            helpers=helpers,
            hooks=hooks,
            instructions=instructions,
            limits=limits,
            max_session_turns=max_session_turns,
            max_turns=max_turns,
            model=model,
            skills=skills,
            temperature=temperature,
            tools=tools,
        )

        return agent_document

