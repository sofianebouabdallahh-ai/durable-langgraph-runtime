from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.activity_view_range import ActivityViewRange
from typing import cast

if TYPE_CHECKING:
  from ..models.agent_row import AgentRow
  from ..models.day import Day
  from ..models.error_row import ErrorRow
  from ..models.model_row import ModelRow
  from ..models.now import Now
  from ..models.tool_row import ToolRow
  from ..models.totals import Totals





T = TypeVar("T", bound="ActivityView")



@_attrs_define
class ActivityView:
    """ 
        Attributes:
            agents (list[AgentRow]):
            days (list[Day]):
            errors (list[ErrorRow]):
            models (list[ModelRow]):
            now (Now):
            range_ (ActivityViewRange):
            tools (list[ToolRow]):
            totals (Totals):
     """

    agents: list[AgentRow]
    days: list[Day]
    errors: list[ErrorRow]
    models: list[ModelRow]
    now: Now
    range_: ActivityViewRange
    tools: list[ToolRow]
    totals: Totals
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_row import AgentRow # noqa: PLC0415
        from ..models.day import Day # noqa: PLC0415
        from ..models.error_row import ErrorRow # noqa: PLC0415
        from ..models.model_row import ModelRow # noqa: PLC0415
        from ..models.now import Now # noqa: PLC0415
        from ..models.tool_row import ToolRow # noqa: PLC0415
        from ..models.totals import Totals # noqa: PLC0415
        agents = []
        for agents_item_data in self.agents:
            agents_item = agents_item_data.to_dict()
            agents.append(agents_item)



        days = []
        for days_item_data in self.days:
            days_item = days_item_data.to_dict()
            days.append(days_item)



        errors = []
        for errors_item_data in self.errors:
            errors_item = errors_item_data.to_dict()
            errors.append(errors_item)



        models = []
        for models_item_data in self.models:
            models_item = models_item_data.to_dict()
            models.append(models_item)



        now = self.now.to_dict()

        range_ = self.range_.value

        tools = []
        for tools_item_data in self.tools:
            tools_item = tools_item_data.to_dict()
            tools.append(tools_item)



        totals = self.totals.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agents": agents,
            "days": days,
            "errors": errors,
            "models": models,
            "now": now,
            "range": range_,
            "tools": tools,
            "totals": totals,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_row import AgentRow # noqa: PLC0415
        from ..models.day import Day # noqa: PLC0415
        from ..models.error_row import ErrorRow # noqa: PLC0415
        from ..models.model_row import ModelRow # noqa: PLC0415
        from ..models.now import Now # noqa: PLC0415
        from ..models.tool_row import ToolRow # noqa: PLC0415
        from ..models.totals import Totals # noqa: PLC0415
        d = dict(src_dict)
        agents = []
        _agents = d.pop("agents")
        for agents_item_data in (_agents):
            agents_item = AgentRow.from_dict(agents_item_data)



            agents.append(agents_item)


        days = []
        _days = d.pop("days")
        for days_item_data in (_days):
            days_item = Day.from_dict(days_item_data)



            days.append(days_item)


        errors = []
        _errors = d.pop("errors")
        for errors_item_data in (_errors):
            errors_item = ErrorRow.from_dict(errors_item_data)



            errors.append(errors_item)


        models = []
        _models = d.pop("models")
        for models_item_data in (_models):
            models_item = ModelRow.from_dict(models_item_data)



            models.append(models_item)


        now = Now.from_dict(d.pop("now"))




        range_ = ActivityViewRange(d.pop("range"))




        tools = []
        _tools = d.pop("tools")
        for tools_item_data in (_tools):
            tools_item = ToolRow.from_dict(tools_item_data)



            tools.append(tools_item)


        totals = Totals.from_dict(d.pop("totals"))




        activity_view = cls(
            agents=agents,
            days=days,
            errors=errors,
            models=models,
            now=now,
            range_=range_,
            tools=tools,
            totals=totals,
        )


        activity_view.additional_properties = d
        return activity_view

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
