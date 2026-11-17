from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.agent_view_source import AgentViewSource
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.agent_view_hooks import AgentViewHooks
  from ..models.agent_view_limits import AgentViewLimits
  from ..models.agent_view_tools_item import AgentViewToolsItem
  from ..models.helper_view import HelperView





T = TypeVar("T", bound="AgentView")



@_attrs_define
class AgentView:
    """ 
        Attributes:
            agent_id (None | UUID): A Studio agent's id (for editing)
            description (str):
            display_name (str): How people see it (falls back to the name)
            helpers (list[HelperView]): The sub-agents in detail
            hidden (bool): A test or example agent: not offered in the UI
            hooks (AgentViewHooks):
            limits (AgentViewLimits):
            max_turns (int):
            model (str):
            name (str):
            source (AgentViewSource): Files in git, or built in the Studio
            subagents (list[str]):
            tools (list[AgentViewToolsItem]):
            version (int):
            prompt (None | str | Unset): GET /agents/{name} only
     """

    agent_id: None | UUID
    description: str
    display_name: str
    helpers: list[HelperView]
    hidden: bool
    hooks: AgentViewHooks
    limits: AgentViewLimits
    max_turns: int
    model: str
    name: str
    source: AgentViewSource
    subagents: list[str]
    tools: list[AgentViewToolsItem]
    version: int
    prompt: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_view_hooks import AgentViewHooks # noqa: PLC0415
        from ..models.agent_view_limits import AgentViewLimits # noqa: PLC0415
        from ..models.agent_view_tools_item import AgentViewToolsItem # noqa: PLC0415
        from ..models.helper_view import HelperView # noqa: PLC0415
        agent_id: None | str
        if isinstance(self.agent_id, UUID):
            agent_id = str(self.agent_id)
        else:
            agent_id = self.agent_id

        description = self.description

        display_name = self.display_name

        helpers = []
        for helpers_item_data in self.helpers:
            helpers_item = helpers_item_data.to_dict()
            helpers.append(helpers_item)



        hidden = self.hidden

        hooks = self.hooks.to_dict()

        limits = self.limits.to_dict()

        max_turns = self.max_turns

        model = self.model

        name = self.name

        source = self.source.value

        subagents = self.subagents



        tools = []
        for tools_item_data in self.tools:
            tools_item = tools_item_data.to_dict()
            tools.append(tools_item)



        version = self.version

        prompt: None | str | Unset
        if isinstance(self.prompt, Unset):
            prompt = UNSET
        else:
            prompt = self.prompt


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent_id": agent_id,
            "description": description,
            "display_name": display_name,
            "helpers": helpers,
            "hidden": hidden,
            "hooks": hooks,
            "limits": limits,
            "max_turns": max_turns,
            "model": model,
            "name": name,
            "source": source,
            "subagents": subagents,
            "tools": tools,
            "version": version,
        })
        if prompt is not UNSET:
            field_dict["prompt"] = prompt

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_view_hooks import AgentViewHooks # noqa: PLC0415
        from ..models.agent_view_limits import AgentViewLimits # noqa: PLC0415
        from ..models.agent_view_tools_item import AgentViewToolsItem # noqa: PLC0415
        from ..models.helper_view import HelperView # noqa: PLC0415
        d = dict(src_dict)
        def _parse_agent_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                agent_id_type_0 = UUID(data)



                return agent_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        agent_id = _parse_agent_id(d.pop("agent_id"))


        description = d.pop("description")

        display_name = d.pop("display_name")

        helpers = []
        _helpers = d.pop("helpers")
        for helpers_item_data in (_helpers):
            helpers_item = HelperView.from_dict(helpers_item_data)



            helpers.append(helpers_item)


        hidden = d.pop("hidden")

        hooks = AgentViewHooks.from_dict(d.pop("hooks"))




        limits = AgentViewLimits.from_dict(d.pop("limits"))




        max_turns = d.pop("max_turns")

        model = d.pop("model")

        name = d.pop("name")

        source = AgentViewSource(d.pop("source"))




        subagents = cast(list[str], d.pop("subagents"))


        tools = []
        _tools = d.pop("tools")
        for tools_item_data in (_tools):
            tools_item = AgentViewToolsItem.from_dict(tools_item_data)



            tools.append(tools_item)


        version = d.pop("version")

        def _parse_prompt(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        prompt = _parse_prompt(d.pop("prompt", UNSET))


        agent_view = cls(
            agent_id=agent_id,
            description=description,
            display_name=display_name,
            helpers=helpers,
            hidden=hidden,
            hooks=hooks,
            limits=limits,
            max_turns=max_turns,
            model=model,
            name=name,
            source=source,
            subagents=subagents,
            tools=tools,
            version=version,
            prompt=prompt,
        )


        agent_view.additional_properties = d
        return agent_view

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
