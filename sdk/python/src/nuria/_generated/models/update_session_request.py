from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from typing import Literal, cast






T = TypeVar("T", bound="UpdateSessionRequest")



@_attrs_define
class UpdateSessionRequest:
    """ 
        Attributes:
            status (Literal['archived'] | None | Unset): Archive (R12.1)
            title (None | str | Unset):
     """

    status: Literal['archived'] | None | Unset = UNSET
    title: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        status: Literal['archived'] | None | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        else:
            status = self.status

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if status is not UNSET:
            field_dict["status"] = status
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_status(data: object) -> Literal['archived'] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            status_type_0 = cast(Literal['archived'] , data)
            if status_type_0 != 'archived':
                raise ValueError(f"status_type_0 must match const 'archived', got '{status_type_0}'")
            return status_type_0
            return cast(Literal['archived'] | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))


        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))


        update_session_request = cls(
            status=status,
            title=title,
        )

        return update_session_request

