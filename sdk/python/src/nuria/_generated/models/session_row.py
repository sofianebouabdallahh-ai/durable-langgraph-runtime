from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="SessionRow")



@_attrs_define
class SessionRow:
    """ 
        Attributes:
            agent (None | str):
            cost (float):
            created_at (datetime.datetime):
            failed (int):
            id (UUID):
            last_activity_at (datetime.datetime):
            messages (int):
            status (str):
            test (bool):
            title (None | str):
            tokens (int):
            turns (int): Turns in range
     """

    agent: None | str
    cost: float
    created_at: datetime.datetime
    failed: int
    id: UUID
    last_activity_at: datetime.datetime
    messages: int
    status: str
    test: bool
    title: None | str
    tokens: int
    turns: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent: None | str
        agent = self.agent

        cost = self.cost

        created_at = self.created_at.isoformat()

        failed = self.failed

        id = str(self.id)

        last_activity_at = self.last_activity_at.isoformat()

        messages = self.messages

        status = self.status

        test = self.test

        title: None | str
        title = self.title

        tokens = self.tokens

        turns = self.turns


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "cost": cost,
            "created_at": created_at,
            "failed": failed,
            "id": id,
            "last_activity_at": last_activity_at,
            "messages": messages,
            "status": status,
            "test": test,
            "title": title,
            "tokens": tokens,
            "turns": turns,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_agent(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        agent = _parse_agent(d.pop("agent"))


        cost = d.pop("cost")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        failed = d.pop("failed")

        id = UUID(d.pop("id"))




        last_activity_at = datetime.datetime.fromisoformat(d.pop("last_activity_at"))




        messages = d.pop("messages")

        status = d.pop("status")

        test = d.pop("test")

        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))


        tokens = d.pop("tokens")

        turns = d.pop("turns")

        session_row = cls(
            agent=agent,
            cost=cost,
            created_at=created_at,
            failed=failed,
            id=id,
            last_activity_at=last_activity_at,
            messages=messages,
            status=status,
            test=test,
            title=title,
            tokens=tokens,
            turns=turns,
        )


        session_row.additional_properties = d
        return session_row

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
