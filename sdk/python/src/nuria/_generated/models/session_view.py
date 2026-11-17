from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="SessionView")



@_attrs_define
class SessionView:
    """ 
        Attributes:
            active_run_id (None | UUID):
            active_run_status (None | str):
            agent (None | str):
            cost (float):
            created_at (datetime.datetime):
            ended_at (datetime.datetime | None):
            id (UUID):
            last_activity_at (datetime.datetime):
            messages (int): Transcript length (the last seq)
            status (str):
            summary (None | str): Stored by the session_end hooks (R15.6)
            title (None | str):
            tokens (int):
     """

    active_run_id: None | UUID
    active_run_status: None | str
    agent: None | str
    cost: float
    created_at: datetime.datetime
    ended_at: datetime.datetime | None
    id: UUID
    last_activity_at: datetime.datetime
    messages: int
    status: str
    summary: None | str
    title: None | str
    tokens: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        active_run_id: None | str
        if isinstance(self.active_run_id, UUID):
            active_run_id = str(self.active_run_id)
        else:
            active_run_id = self.active_run_id

        active_run_status: None | str
        active_run_status = self.active_run_status

        agent: None | str
        agent = self.agent

        cost = self.cost

        created_at = self.created_at.isoformat()

        ended_at: None | str
        if isinstance(self.ended_at, datetime.datetime):
            ended_at = self.ended_at.isoformat()
        else:
            ended_at = self.ended_at

        id = str(self.id)

        last_activity_at = self.last_activity_at.isoformat()

        messages = self.messages

        status = self.status

        summary: None | str
        summary = self.summary

        title: None | str
        title = self.title

        tokens = self.tokens


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "active_run_id": active_run_id,
            "active_run_status": active_run_status,
            "agent": agent,
            "cost": cost,
            "created_at": created_at,
            "ended_at": ended_at,
            "id": id,
            "last_activity_at": last_activity_at,
            "messages": messages,
            "status": status,
            "summary": summary,
            "title": title,
            "tokens": tokens,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_active_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                active_run_id_type_0 = UUID(data)



                return active_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        active_run_id = _parse_active_run_id(d.pop("active_run_id"))


        def _parse_active_run_status(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        active_run_status = _parse_active_run_status(d.pop("active_run_status"))


        def _parse_agent(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        agent = _parse_agent(d.pop("agent"))


        cost = d.pop("cost")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        def _parse_ended_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                ended_at_type_0 = datetime.datetime.fromisoformat(data)



                return ended_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        ended_at = _parse_ended_at(d.pop("ended_at"))


        id = UUID(d.pop("id"))




        last_activity_at = datetime.datetime.fromisoformat(d.pop("last_activity_at"))




        messages = d.pop("messages")

        status = d.pop("status")

        def _parse_summary(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        summary = _parse_summary(d.pop("summary"))


        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))


        tokens = d.pop("tokens")

        session_view = cls(
            active_run_id=active_run_id,
            active_run_status=active_run_status,
            agent=agent,
            cost=cost,
            created_at=created_at,
            ended_at=ended_at,
            id=id,
            last_activity_at=last_activity_at,
            messages=messages,
            status=status,
            summary=summary,
            title=title,
            tokens=tokens,
        )


        session_view.additional_properties = d
        return session_view

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
