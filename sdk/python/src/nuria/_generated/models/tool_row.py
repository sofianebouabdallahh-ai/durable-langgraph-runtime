from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="ToolRow")



@_attrs_define
class ToolRow:
    """ 
        Attributes:
            cached (int):
            calls (int):
            failed (int):
            p95_ms (float | None):
            tool (None | str):
     """

    cached: int
    calls: int
    failed: int
    p95_ms: float | None
    tool: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        cached = self.cached

        calls = self.calls

        failed = self.failed

        p95_ms: float | None
        p95_ms = self.p95_ms

        tool: None | str
        tool = self.tool


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "cached": cached,
            "calls": calls,
            "failed": failed,
            "p95_ms": p95_ms,
            "tool": tool,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cached = d.pop("cached")

        calls = d.pop("calls")

        failed = d.pop("failed")

        def _parse_p95_ms(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p95_ms = _parse_p95_ms(d.pop("p95_ms"))


        def _parse_tool(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        tool = _parse_tool(d.pop("tool"))


        tool_row = cls(
            cached=cached,
            calls=calls,
            failed=failed,
            p95_ms=p95_ms,
            tool=tool,
        )


        tool_row.additional_properties = d
        return tool_row

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
