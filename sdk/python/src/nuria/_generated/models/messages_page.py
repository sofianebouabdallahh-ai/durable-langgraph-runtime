from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.message_view import MessageView





T = TypeVar("T", bound="MessagesPage")



@_attrs_define
class MessagesPage:
    """ 
        Attributes:
            messages (list[MessageView]):
            next_after_seq (int | None):
     """

    messages: list[MessageView]
    next_after_seq: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.message_view import MessageView # noqa: PLC0415
        messages = []
        for messages_item_data in self.messages:
            messages_item = messages_item_data.to_dict()
            messages.append(messages_item)



        next_after_seq: int | None
        next_after_seq = self.next_after_seq


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "messages": messages,
            "next_after_seq": next_after_seq,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_view import MessageView # noqa: PLC0415
        d = dict(src_dict)
        messages = []
        _messages = d.pop("messages")
        for messages_item_data in (_messages):
            messages_item = MessageView.from_dict(messages_item_data)



            messages.append(messages_item)


        def _parse_next_after_seq(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        next_after_seq = _parse_next_after_seq(d.pop("next_after_seq"))


        messages_page = cls(
            messages=messages,
            next_after_seq=next_after_seq,
        )


        messages_page.additional_properties = d
        return messages_page

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
