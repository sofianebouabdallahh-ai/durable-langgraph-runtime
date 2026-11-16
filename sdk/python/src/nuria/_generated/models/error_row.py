from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="ErrorRow")



@_attrs_define
class ErrorRow:
    """ 
        Attributes:
            agent (str):
            at (datetime.datetime):
            count (int):
            reason (None | str):
            run_id (UUID): The latest failed turn
            session_id (None | UUID):
     """

    agent: str
    at: datetime.datetime
    count: int
    reason: None | str
    run_id: UUID
    session_id: None | UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        at = self.at.isoformat()

        count = self.count

        reason: None | str
        reason = self.reason

        run_id = str(self.run_id)

        session_id: None | str
        if isinstance(self.session_id, UUID):
            session_id = str(self.session_id)
        else:
            session_id = self.session_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "at": at,
            "count": count,
            "reason": reason,
            "run_id": run_id,
            "session_id": session_id,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        at = datetime.datetime.fromisoformat(d.pop("at"))




        count = d.pop("count")

        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        run_id = UUID(d.pop("run_id"))




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


        error_row = cls(
            agent=agent,
            at=at,
            count=count,
            reason=reason,
            run_id=run_id,
            session_id=session_id,
        )


        error_row.additional_properties = d
        return error_row

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
