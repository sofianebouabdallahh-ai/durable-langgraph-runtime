from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="SearchTest")



@_attrs_define
class SearchTest:
    """ 
        Attributes:
            query (str | Unset):  Default: 'weather today'.
     """

    query: str | Unset = 'weather today'





    def to_dict(self) -> dict[str, Any]:
        query = self.query


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if query is not UNSET:
            field_dict["query"] = query

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        query = d.pop("query", UNSET)

        search_test = cls(
            query=query,
        )

        return search_test

