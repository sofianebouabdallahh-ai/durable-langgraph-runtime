from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
import datetime






T = TypeVar("T", bound="AgentRow")



@_attrs_define
class AgentRow:
    """ 
        Attributes:
            agent (str):
            cost (float):
            disliked (int): Replies given 👎
            failed (int):
            last_turn (datetime.datetime | None):
            liked (int): Replies given 👍
            p50_s (float | None): Median turn time
            p95_s (float | None):
            tokens (int):
            turns (int):
     """

    agent: str
    cost: float
    disliked: int
    failed: int
    last_turn: datetime.datetime | None
    liked: int
    p50_s: float | None
    p95_s: float | None
    tokens: int
    turns: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        cost = self.cost

        disliked = self.disliked

        failed = self.failed

        last_turn: None | str
        if isinstance(self.last_turn, datetime.datetime):
            last_turn = self.last_turn.isoformat()
        else:
            last_turn = self.last_turn

        liked = self.liked

        p50_s: float | None
        p50_s = self.p50_s

        p95_s: float | None
        p95_s = self.p95_s

        tokens = self.tokens

        turns = self.turns


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "cost": cost,
            "disliked": disliked,
            "failed": failed,
            "last_turn": last_turn,
            "liked": liked,
            "p50_s": p50_s,
            "p95_s": p95_s,
            "tokens": tokens,
            "turns": turns,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        cost = d.pop("cost")

        disliked = d.pop("disliked")

        failed = d.pop("failed")

        def _parse_last_turn(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_turn_type_0 = datetime.datetime.fromisoformat(data)



                return last_turn_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_turn = _parse_last_turn(d.pop("last_turn"))


        liked = d.pop("liked")

        def _parse_p50_s(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p50_s = _parse_p50_s(d.pop("p50_s"))


        def _parse_p95_s(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p95_s = _parse_p95_s(d.pop("p95_s"))


        tokens = d.pop("tokens")

        turns = d.pop("turns")

        agent_row = cls(
            agent=agent,
            cost=cost,
            disliked=disliked,
            failed=failed,
            last_turn=last_turn,
            liked=liked,
            p50_s=p50_s,
            p95_s=p95_s,
            tokens=tokens,
            turns=turns,
        )


        agent_row.additional_properties = d
        return agent_row

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
