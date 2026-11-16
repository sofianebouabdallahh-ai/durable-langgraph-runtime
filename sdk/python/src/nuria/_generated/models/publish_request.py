from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="PublishRequest")



@_attrs_define
class PublishRequest:
    """ 
        Attributes:
            changelog (None | str | Unset):
     """

    changelog: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        changelog: None | str | Unset
        if isinstance(self.changelog, Unset):
            changelog = UNSET
        else:
            changelog = self.changelog


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if changelog is not UNSET:
            field_dict["changelog"] = changelog

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_changelog(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        changelog = _parse_changelog(d.pop("changelog", UNSET))


        publish_request = cls(
            changelog=changelog,
        )

        return publish_request

