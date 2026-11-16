from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.add_connection_kind import AddConnectionKind
from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="AddConnection")



@_attrs_define
class AddConnection:
    """ 
        Attributes:
            base_url (str):
            display_name (str):
            kind (AddConnectionKind):
            api_key (None | str | Unset):
            models (list[str] | Unset):
     """

    base_url: str
    display_name: str
    kind: AddConnectionKind
    api_key: None | str | Unset = UNSET
    models: list[str] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        base_url = self.base_url

        display_name = self.display_name

        kind = self.kind.value

        api_key: None | str | Unset
        if isinstance(self.api_key, Unset):
            api_key = UNSET
        else:
            api_key = self.api_key

        models: list[str] | Unset = UNSET
        if not isinstance(self.models, Unset):
            models = self.models




        field_dict: dict[str, Any] = {}

        field_dict.update({
            "base_url": base_url,
            "display_name": display_name,
            "kind": kind,
        })
        if api_key is not UNSET:
            field_dict["api_key"] = api_key
        if models is not UNSET:
            field_dict["models"] = models

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        base_url = d.pop("base_url")

        display_name = d.pop("display_name")

        kind = AddConnectionKind(d.pop("kind"))




        def _parse_api_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        api_key = _parse_api_key(d.pop("api_key", UNSET))


        models = cast(list[str], d.pop("models", UNSET))


        add_connection = cls(
            base_url=base_url,
            display_name=display_name,
            kind=kind,
            api_key=api_key,
            models=models,
        )

        return add_connection

