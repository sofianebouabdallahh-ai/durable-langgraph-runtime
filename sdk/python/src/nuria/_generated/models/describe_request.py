from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="DescribeRequest")



@_attrs_define
class DescribeRequest:
    """ 
        Attributes:
            description (str): The assistant the person wants
     """

    description: str





    def to_dict(self) -> dict[str, Any]:
        description = self.description


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "description": description,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        description = d.pop("description")

        describe_request = cls(
            description=description,
        )

        return describe_request

