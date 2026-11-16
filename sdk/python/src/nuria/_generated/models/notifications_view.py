from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.notification_view import NotificationView





T = TypeVar("T", bound="NotificationsView")



@_attrs_define
class NotificationsView:
    """ 
        Attributes:
            notifications (list[NotificationView]):
            signed (bool): Deliveries carry a webhook-signature
            webhook (None | str): The webhook's host, if one is set up
     """

    notifications: list[NotificationView]
    signed: bool
    webhook: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.notification_view import NotificationView # noqa: PLC0415
        notifications = []
        for notifications_item_data in self.notifications:
            notifications_item = notifications_item_data.to_dict()
            notifications.append(notifications_item)



        signed = self.signed

        webhook: None | str
        webhook = self.webhook


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "notifications": notifications,
            "signed": signed,
            "webhook": webhook,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.notification_view import NotificationView # noqa: PLC0415
        d = dict(src_dict)
        notifications = []
        _notifications = d.pop("notifications")
        for notifications_item_data in (_notifications):
            notifications_item = NotificationView.from_dict(notifications_item_data)



            notifications.append(notifications_item)


        signed = d.pop("signed")

        def _parse_webhook(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        webhook = _parse_webhook(d.pop("webhook"))


        notifications_view = cls(
            notifications=notifications,
            signed=signed,
            webhook=webhook,
        )


        notifications_view.additional_properties = d
        return notifications_view

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
