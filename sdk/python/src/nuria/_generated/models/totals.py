from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.approvals import Approvals





T = TypeVar("T", bound="Totals")



@_attrs_define
class Totals:
    """ 
        Attributes:
            approvals (Approvals):
            chats (int):
            cost (float):
            failed (int):
            helpers (int):
            model_calls (int):
            tokens (int):
            tool_calls (int):
            turns (int):
     """

    approvals: Approvals
    chats: int
    cost: float
    failed: int
    helpers: int
    model_calls: int
    tokens: int
    tool_calls: int
    turns: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.approvals import Approvals # noqa: PLC0415
        approvals = self.approvals.to_dict()

        chats = self.chats

        cost = self.cost

        failed = self.failed

        helpers = self.helpers

        model_calls = self.model_calls

        tokens = self.tokens

        tool_calls = self.tool_calls

        turns = self.turns


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "approvals": approvals,
            "chats": chats,
            "cost": cost,
            "failed": failed,
            "helpers": helpers,
            "model_calls": model_calls,
            "tokens": tokens,
            "tool_calls": tool_calls,
            "turns": turns,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.approvals import Approvals # noqa: PLC0415
        d = dict(src_dict)
        approvals = Approvals.from_dict(d.pop("approvals"))




        chats = d.pop("chats")

        cost = d.pop("cost")

        failed = d.pop("failed")

        helpers = d.pop("helpers")

        model_calls = d.pop("model_calls")

        tokens = d.pop("tokens")

        tool_calls = d.pop("tool_calls")

        turns = d.pop("turns")

        totals = cls(
            approvals=approvals,
            chats=chats,
            cost=cost,
            failed=failed,
            helpers=helpers,
            model_calls=model_calls,
            tokens=tokens,
            tool_calls=tool_calls,
            turns=turns,
        )


        totals.additional_properties = d
        return totals

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
