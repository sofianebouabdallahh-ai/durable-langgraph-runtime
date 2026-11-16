from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="NoteView")



@_attrs_define
class NoteView:
    """ 
        Attributes:
            forgotten_at (datetime.datetime | None): When the agent was asked to forget it
            helper (None | str): The helper that keeps it; None: the agent itself
            id (str):
            saved_at (datetime.datetime):
            session_id (None | UUID): The chat it was saved in, if it's kept
            text (str):
     """

    forgotten_at: datetime.datetime | None
    helper: None | str
    id: str
    saved_at: datetime.datetime
    session_id: None | UUID
    text: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        forgotten_at: None | str
        if isinstance(self.forgotten_at, datetime.datetime):
            forgotten_at = self.forgotten_at.isoformat()
        else:
            forgotten_at = self.forgotten_at

        helper: None | str
        helper = self.helper

        id = self.id

        saved_at = self.saved_at.isoformat()

        session_id: None | str
        if isinstance(self.session_id, UUID):
            session_id = str(self.session_id)
        else:
            session_id = self.session_id

        text = self.text


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "forgotten_at": forgotten_at,
            "helper": helper,
            "id": id,
            "saved_at": saved_at,
            "session_id": session_id,
            "text": text,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_forgotten_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                forgotten_at_type_0 = datetime.datetime.fromisoformat(data)



                return forgotten_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        forgotten_at = _parse_forgotten_at(d.pop("forgotten_at"))


        def _parse_helper(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        helper = _parse_helper(d.pop("helper"))


        id = d.pop("id")

        saved_at = datetime.datetime.fromisoformat(d.pop("saved_at"))




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


        text = d.pop("text")

        note_view = cls(
            forgotten_at=forgotten_at,
            helper=helper,
            id=id,
            saved_at=saved_at,
            session_id=session_id,
            text=text,
        )


        note_view.additional_properties = d
        return note_view

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
