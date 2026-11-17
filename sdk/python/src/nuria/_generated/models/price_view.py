from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.price_view_source import PriceViewSource






T = TypeVar("T", bound="PriceView")



@_attrs_define
class PriceView:
    """ 
        Attributes:
            input_per_mtok (float): USD per 1 million input tokens
            output_per_mtok (float): USD per 1 million output tokens
            source (PriceViewSource): Where the price comes from: set here, MODEL_PRICES, Nuria's price list (dated), free
                (a model on this machine or network), or an estimate (a deliberately high default for a model with no known
                price: set its price)
     """

    input_per_mtok: float
    output_per_mtok: float
    source: PriceViewSource
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        input_per_mtok = self.input_per_mtok

        output_per_mtok = self.output_per_mtok

        source = self.source.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "input_per_mtok": input_per_mtok,
            "output_per_mtok": output_per_mtok,
            "source": source,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        input_per_mtok = d.pop("input_per_mtok")

        output_per_mtok = d.pop("output_per_mtok")

        source = PriceViewSource(d.pop("source"))




        price_view = cls(
            input_per_mtok=input_per_mtok,
            output_per_mtok=output_per_mtok,
            source=source,
        )


        price_view.additional_properties = d
        return price_view

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
