from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ModelRow")



@_attrs_define
class ModelRow:
    """ 
        Attributes:
            avg_ms (int | None): Average time per call
            calls (int):
            cost (float):
            model (str):
            tokens_in (int):
            tokens_out (int):
            estimated (bool | Unset): Some calls had no known price and were priced by a deliberately high estimate: set the
                model's price in Settings → Models Default: False.
     """

    avg_ms: int | None
    calls: int
    cost: float
    model: str
    tokens_in: int
    tokens_out: int
    estimated: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        avg_ms: int | None
        avg_ms = self.avg_ms

        calls = self.calls

        cost = self.cost

        model = self.model

        tokens_in = self.tokens_in

        tokens_out = self.tokens_out

        estimated = self.estimated


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "avg_ms": avg_ms,
            "calls": calls,
            "cost": cost,
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
        def _parse_avg_ms(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        avg_ms = _parse_avg_ms(d.pop("avg_ms"))


        calls = d.pop("calls")

        cost = d.pop("cost")

        model = d.pop("model")

        tokens_in = d.pop("tokens_in")

        tokens_out = d.pop("tokens_out")

        estimated = d.pop("estimated", UNSET)

        model_row = cls(
            avg_ms=avg_ms,
            calls=calls,
            cost=cost,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated=estimated,
        )


        model_row.additional_properties = d
        return model_row

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
