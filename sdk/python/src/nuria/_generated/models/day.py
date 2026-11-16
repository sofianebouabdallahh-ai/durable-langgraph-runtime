from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
import datetime

if TYPE_CHECKING:
  from ..models.day_by_agent import DayByAgent





T = TypeVar("T", bound="Day")



@_attrs_define
class Day:
    """ 
        Attributes:
            by_agent (DayByAgent): Turns per agent that day
            cost (float):
            day (datetime.date):
            failed (int):
            turns (int):
     """

    by_agent: DayByAgent
    cost: float
    day: datetime.date
    failed: int
    turns: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.day_by_agent import DayByAgent # noqa: PLC0415
        by_agent = self.by_agent.to_dict()

        cost = self.cost

        day = self.day.isoformat()

        failed = self.failed

        turns = self.turns


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "by_agent": by_agent,
            "cost": cost,
            "day": day,
            "failed": failed,
            "turns": turns,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.day_by_agent import DayByAgent # noqa: PLC0415
        d = dict(src_dict)
        by_agent = DayByAgent.from_dict(d.pop("by_agent"))




        cost = d.pop("cost")

        day = datetime.date.fromisoformat(d.pop("day"))




        failed = d.pop("failed")

        turns = d.pop("turns")

        day = cls(
            by_agent=by_agent,
            cost=cost,
            day=day,
            failed=failed,
            turns=turns,
        )


        day.additional_properties = d
        return day

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
