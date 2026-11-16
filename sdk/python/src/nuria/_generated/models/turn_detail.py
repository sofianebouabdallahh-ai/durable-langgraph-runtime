from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.model_usage import ModelUsage





T = TypeVar("T", bound="TurnDetail")



@_attrs_define
class TurnDetail:
    """ 
        Attributes:
            agent (None | str):
            agent_version (int | None):
            cost (float):
            created_at (datetime.datetime):
            duration_s (float | None):
            id (UUID):
            model_calls (int):
            models (list[str]):
            reason (None | str):
            reclaims (int):
            session_id (None | UUID):
            session_title (None | str):
            status (str):
            steps (int):
            test (bool | None):
            tokens (int):
            tool_calls (int):
            usage (list[ModelUsage]): Its model calls, per model
            rating (int | None | Unset): 👍 1, 👎 -1, or not rated
     """

    agent: None | str
    agent_version: int | None
    cost: float
    created_at: datetime.datetime
    duration_s: float | None
    id: UUID
    model_calls: int
    models: list[str]
    reason: None | str
    reclaims: int
    session_id: None | UUID
    session_title: None | str
    status: str
    steps: int
    test: bool | None
    tokens: int
    tool_calls: int
    usage: list[ModelUsage]
    rating: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.model_usage import ModelUsage # noqa: PLC0415
        agent: None | str
        agent = self.agent

        agent_version: int | None
        agent_version = self.agent_version

        cost = self.cost

        created_at = self.created_at.isoformat()

        duration_s: float | None
        duration_s = self.duration_s

        id = str(self.id)

        model_calls = self.model_calls

        models = self.models



        reason: None | str
        reason = self.reason

        reclaims = self.reclaims

        session_id: None | str
        if isinstance(self.session_id, UUID):
            session_id = str(self.session_id)
        else:
            session_id = self.session_id

        session_title: None | str
        session_title = self.session_title

        status = self.status

        steps = self.steps

        test: bool | None
        test = self.test

        tokens = self.tokens

        tool_calls = self.tool_calls

        usage = []
        for usage_item_data in self.usage:
            usage_item = usage_item_data.to_dict()
            usage.append(usage_item)



        rating: int | None | Unset
        if isinstance(self.rating, Unset):
            rating = UNSET
        else:
            rating = self.rating


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "agent_version": agent_version,
            "cost": cost,
            "created_at": created_at,
            "duration_s": duration_s,
            "id": id,
            "model_calls": model_calls,
            "models": models,
            "reason": reason,
            "reclaims": reclaims,
            "session_id": session_id,
            "session_title": session_title,
            "status": status,
            "steps": steps,
            "test": test,
            "tokens": tokens,
            "tool_calls": tool_calls,
            "usage": usage,
        })
        if rating is not UNSET:
            field_dict["rating"] = rating

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.model_usage import ModelUsage # noqa: PLC0415
        d = dict(src_dict)
        def _parse_agent(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        agent = _parse_agent(d.pop("agent"))


        def _parse_agent_version(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        agent_version = _parse_agent_version(d.pop("agent_version"))


        cost = d.pop("cost")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        def _parse_duration_s(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        duration_s = _parse_duration_s(d.pop("duration_s"))


        id = UUID(d.pop("id"))




        model_calls = d.pop("model_calls")

        models = cast(list[str], d.pop("models"))


        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        reclaims = d.pop("reclaims")

        def _parse_session_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                session_id_type_0 = UUID(data)



                return session_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        session_id = _parse_session_id(d.pop("session_id"))


        def _parse_session_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        session_title = _parse_session_title(d.pop("session_title"))


        status = d.pop("status")

        steps = d.pop("steps")

        def _parse_test(data: object) -> bool | None:
            if data is None:
                return data
            return cast(bool | None, data)

        test = _parse_test(d.pop("test"))


        tokens = d.pop("tokens")

        tool_calls = d.pop("tool_calls")

        usage = []
        _usage = d.pop("usage")
        for usage_item_data in (_usage):
            usage_item = ModelUsage.from_dict(usage_item_data)



            usage.append(usage_item)


        def _parse_rating(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        rating = _parse_rating(d.pop("rating", UNSET))


        turn_detail = cls(
            agent=agent,
            agent_version=agent_version,
            cost=cost,
            created_at=created_at,
            duration_s=duration_s,
            id=id,
            model_calls=model_calls,
            models=models,
            reason=reason,
            reclaims=reclaims,
            session_id=session_id,
            session_title=session_title,
            status=status,
            steps=steps,
            test=test,
            tokens=tokens,
            tool_calls=tool_calls,
            usage=usage,
            rating=rating,
        )


        turn_detail.additional_properties = d
        return turn_detail

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
