from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="StopRequest")



@_attrs_define
class StopRequest:
    """ 
        Attributes:
            agent (None | str | Unset): None: every agent
            reason (None | str | Unset):
     """

    agent: None | str | Unset = UNSET
    reason: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        agent: None | str | Unset
        if isinstance(self.agent, Unset):
            agent = UNSET
        else:
            agent = self.agent

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if agent is not UNSET:
            field_dict["agent"] = agent
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_agent(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        agent = _parse_agent(d.pop("agent", UNSET))


        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))


        stop_request = cls(
            agent=agent,
            reason=reason,
        )

        return stop_request

