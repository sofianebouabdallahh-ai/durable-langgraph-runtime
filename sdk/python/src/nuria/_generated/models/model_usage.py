from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="ModelUsage")



@_attrs_define
class ModelUsage:
    """ 
        Attributes:
            calls (int):
            cost (float):
            duration_ms (int):
            model (str):
            tokens_in (int):
            tokens_out (int):
            estimated (bool | Unset): Priced by the estimate for a model with no known price Default: False.
     """

    calls: int
    cost: float
    duration_ms: int
    model: str
    tokens_in: int
    tokens_out: int
    estimated: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        calls = self.calls

        cost = self.cost

        duration_ms = self.duration_ms

        model = self.model

        tokens_in = self.tokens_in

        tokens_out = self.tokens_out

        estimated = self.estimated


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "calls": calls,
            "cost": cost,
            "duration_ms": duration_ms,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })
        if estimated is not UNSET:
            field_dict["estimated"] = estimated

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        calls = d.pop("calls")

        cost = d.pop("cost")

        duration_ms = d.pop("duration_ms")

        model = d.pop("model")

        tokens_in = d.pop("tokens_in")

        tokens_out = d.pop("tokens_out")

        estimated = d.pop("estimated", UNSET)

        model_usage = cls(
            calls=calls,
            cost=cost,
            duration_ms=duration_ms,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated=estimated,
        )


        model_usage.additional_properties = d
        return model_usage

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
