from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="PriceIn")



@_attrs_define
class PriceIn:
    """ 
        Attributes:
            input_per_mtok (float):
            output_per_mtok (float):
     """

    input_per_mtok: float
    output_per_mtok: float





    def to_dict(self) -> dict[str, Any]:
        input_per_mtok = self.input_per_mtok

        output_per_mtok = self.output_per_mtok


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "input_per_mtok": input_per_mtok,
            "output_per_mtok": output_per_mtok,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        input_per_mtok = d.pop("input_per_mtok")

        output_per_mtok = d.pop("output_per_mtok")

        price_in = cls(
            input_per_mtok=input_per_mtok,
            output_per_mtok=output_per_mtok,
        )

        return price_in

