from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.message_view_content import MessageViewContent





T = TypeVar("T", bound="MessageView")



@_attrs_define
class MessageView:
    """ 
        Attributes:
            content (MessageViewContent):
            created_at (datetime.datetime):
            message_id (str):
            role (str):
            run_id (None | UUID):
            seq (int):
            type_ (str):
     """

    content: MessageViewContent
    created_at: datetime.datetime
    message_id: str
    role: str
    run_id: None | UUID
    seq: int
    type_: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.message_view_content import MessageViewContent # noqa: PLC0415
        content = self.content.to_dict()

        created_at = self.created_at.isoformat()

        message_id = self.message_id

        role = self.role

        run_id: None | str
        if isinstance(self.run_id, UUID):
            run_id = str(self.run_id)
        else:
            run_id = self.run_id

        seq = self.seq

        type_ = self.type_


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "content": content,
            "created_at": created_at,
            "message_id": message_id,
            "role": role,
            "run_id": run_id,
            "seq": seq,
            "type": type_,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_view_content import MessageViewContent # noqa: PLC0415
        d = dict(src_dict)
        content = MessageViewContent.from_dict(d.pop("content"))




        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        message_id = d.pop("message_id")

        role = d.pop("role")

        def _parse_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                run_id_type_0 = UUID(data)



                return run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        run_id = _parse_run_id(d.pop("run_id"))


        seq = d.pop("seq")

        type_ = d.pop("type")

        message_view = cls(
            content=content,
            created_at=created_at,
            message_id=message_id,
            role=role,
            run_id=run_id,
            seq=seq,
            type_=type_,
        )


        message_view.additional_properties = d
        return message_view

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
