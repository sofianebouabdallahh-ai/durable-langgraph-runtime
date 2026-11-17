from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="AddServer")



@_attrs_define
class AddServer:
    """ 
        Attributes:
            display_name (str):
            url (str):
            header_name (str | Unset):  Default: 'Authorization'.
            token (None | str | Unset):
     """

    display_name: str
    url: str
    header_name: str | Unset = 'Authorization'
    token: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        url = self.url

        header_name = self.header_name

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "display_name": display_name,
            "url": url,
        })
        if header_name is not UNSET:
            field_dict["header_name"] = header_name
        if token is not UNSET:
            field_dict["token"] = token

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        url = d.pop("url")

        header_name = d.pop("header_name", UNSET)

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))


        add_server = cls(
            display_name=display_name,
            url=url,
            header_name=header_name,
            token=token,
        )

        return add_server

