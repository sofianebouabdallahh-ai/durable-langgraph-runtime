from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="CreateAgentRequest")



@_attrs_define
class CreateAgentRequest:
    """ 
        Attributes:
            display_name (str):
            copy_of (None | str | Unset): An agent to start from (its name)
            description (str | Unset):  Default: ''.
     """

    display_name: str
    copy_of: None | str | Unset = UNSET
    description: str | Unset = ''





    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        copy_of: None | str | Unset
        if isinstance(self.copy_of, Unset):
            copy_of = UNSET
        else:
            copy_of = self.copy_of

        description = self.description


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "display_name": display_name,
        })
        if copy_of is not UNSET:
            field_dict["copy_of"] = copy_of
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        def _parse_copy_of(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        copy_of = _parse_copy_of(d.pop("copy_of", UNSET))


        description = d.pop("description", UNSET)

        create_agent_request = cls(
            display_name=display_name,
            copy_of=copy_of,
            description=description,
        )

        return create_agent_request

