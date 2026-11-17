from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.feedback_view_rating import FeedbackViewRating
from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="FeedbackView")



@_attrs_define
class FeedbackView:
    """ 
        Attributes:
            agent (None | str):
            agent_version (int | None):
            rating (FeedbackViewRating):
            reason (None | str):
            run_id (UUID):
            updated_at (datetime.datetime):
     """

    agent: None | str
    agent_version: int | None
    rating: FeedbackViewRating
    reason: None | str
    run_id: UUID
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent: None | str
        agent = self.agent

        agent_version: int | None
        agent_version = self.agent_version

        rating = self.rating.value

        reason: None | str
        reason = self.reason

        run_id = str(self.run_id)

        updated_at = self.updated_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "agent_version": agent_version,
            "rating": rating,
            "reason": reason,
            "run_id": run_id,
            "updated_at": updated_at,
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


        def _parse_agent_version(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        agent_version = _parse_agent_version(d.pop("agent_version"))


        rating = FeedbackViewRating(d.pop("rating"))




        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        run_id = UUID(d.pop("run_id"))




        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))




        feedback_view = cls(
            agent=agent,
            agent_version=agent_version,
            rating=rating,
            reason=reason,
            run_id=run_id,
            updated_at=updated_at,
        )


        feedback_view.additional_properties = d
        return feedback_view

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
