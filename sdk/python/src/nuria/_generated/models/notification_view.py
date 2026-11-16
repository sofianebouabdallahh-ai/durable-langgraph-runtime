from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.notification_view_status import NotificationViewStatus
from typing import cast
import datetime






T = TypeVar("T", bound="NotificationView")



@_attrs_define
class NotificationView:
    """ 
        Attributes:
            agent (None | str):
            attempts (int):
            created_at (datetime.datetime):
            delivered_at (datetime.datetime | None):
            id (str): The notification's id, as the chat shows it
            last_error (None | str):
            last_status (int | None): The webhook's last HTTP status
            message (str): Its first 300 characters
            status (NotificationViewStatus):
            to (str):
     """

    agent: None | str
    attempts: int
    created_at: datetime.datetime
    delivered_at: datetime.datetime | None
    id: str
    last_error: None | str
    last_status: int | None
    message: str
    status: NotificationViewStatus
    to: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent: None | str
        agent = self.agent

        attempts = self.attempts

        created_at = self.created_at.isoformat()

        delivered_at: None | str
        if isinstance(self.delivered_at, datetime.datetime):
            delivered_at = self.delivered_at.isoformat()
        else:
            delivered_at = self.delivered_at

        id = self.id

        last_error: None | str
        last_error = self.last_error

        last_status: int | None
        last_status = self.last_status

        message = self.message

        status = self.status.value

        to = self.to


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "attempts": attempts,
            "created_at": created_at,
            "delivered_at": delivered_at,
            "id": id,
            "last_error": last_error,
            "last_status": last_status,
            "message": message,
            "status": status,
            "to": to,
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


        attempts = d.pop("attempts")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        def _parse_delivered_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                delivered_at_type_0 = datetime.datetime.fromisoformat(data)



                return delivered_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        delivered_at = _parse_delivered_at(d.pop("delivered_at"))


        id = d.pop("id")

        def _parse_last_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_error = _parse_last_error(d.pop("last_error"))


        def _parse_last_status(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        last_status = _parse_last_status(d.pop("last_status"))


        message = d.pop("message")

        status = NotificationViewStatus(d.pop("status"))




        to = d.pop("to")

        notification_view = cls(
            agent=agent,
            attempts=attempts,
            created_at=created_at,
            delivered_at=delivered_at,
            id=id,
            last_error=last_error,
            last_status=last_status,
            message=message,
            status=status,
            to=to,
        )


        notification_view.additional_properties = d
        return notification_view

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
