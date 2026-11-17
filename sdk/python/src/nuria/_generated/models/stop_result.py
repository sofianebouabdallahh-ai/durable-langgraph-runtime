from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
import datetime

if TYPE_CHECKING:
  from ..models.switch_view import SwitchView





T = TypeVar("T", bound="StopResult")



@_attrs_define
class StopResult:
    """ 
        Attributes:
            agents (list[SwitchView]): Agents switched off one by one
            all_off (bool): Every agent is stopped
            cancelled (int): Runs stopped (their helpers and children with them)
            reason (None | str):
            since (datetime.datetime | None):
     """

    agents: list[SwitchView]
    all_off: bool
    cancelled: int
    reason: None | str
    since: datetime.datetime | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.switch_view import SwitchView # noqa: PLC0415
        agents = []
        for agents_item_data in self.agents:
            agents_item = agents_item_data.to_dict()
            agents.append(agents_item)



        all_off = self.all_off

        cancelled = self.cancelled

        reason: None | str
        reason = self.reason

        since: None | str
        if isinstance(self.since, datetime.datetime):
            since = self.since.isoformat()
        else:
            since = self.since


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agents": agents,
            "all_off": all_off,
            "cancelled": cancelled,
            "reason": reason,
            "since": since,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.switch_view import SwitchView # noqa: PLC0415
        d = dict(src_dict)
        agents = []
        _agents = d.pop("agents")
        for agents_item_data in (_agents):
            agents_item = SwitchView.from_dict(agents_item_data)



            agents.append(agents_item)


        all_off = d.pop("all_off")

        cancelled = d.pop("cancelled")

        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        def _parse_since(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                since_type_0 = datetime.datetime.fromisoformat(data)



                return since_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        since = _parse_since(d.pop("since"))


        stop_result = cls(
            agents=agents,
            all_off=all_off,
            cancelled=cancelled,
            reason=reason,
            since=since,
        )


        stop_result.additional_properties = d
        return stop_result

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
