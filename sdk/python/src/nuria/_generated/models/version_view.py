from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.version_view_state import VersionViewState
from typing import cast
import datetime






T = TypeVar("T", bound="VersionView")



@_attrs_define
class VersionView:
    """ 
        Attributes:
            changelog (None | str):
            created_at (datetime.datetime):
            number (int):
            published_at (datetime.datetime | None):
            state (VersionViewState):
     """

    changelog: None | str
    created_at: datetime.datetime
    number: int
    published_at: datetime.datetime | None
    state: VersionViewState
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        changelog: None | str
        changelog = self.changelog

        created_at = self.created_at.isoformat()

        number = self.number

        published_at: None | str
        if isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        state = self.state.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "changelog": changelog,
            "created_at": created_at,
            "number": number,
            "published_at": published_at,
            "state": state,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_changelog(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        changelog = _parse_changelog(d.pop("changelog"))


        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        number = d.pop("number")

        def _parse_published_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_at_type_0 = datetime.datetime.fromisoformat(data)



                return published_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        published_at = _parse_published_at(d.pop("published_at"))


        state = VersionViewState(d.pop("state"))




        version_view = cls(
            changelog=changelog,
            created_at=created_at,
            number=number,
            published_at=published_at,
            state=state,
        )


        version_view.additional_properties = d
        return version_view

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
