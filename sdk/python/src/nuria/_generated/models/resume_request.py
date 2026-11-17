from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ResumeRequest")



@_attrs_define
class ResumeRequest:
    """ 
        Attributes:
            agent (None | str | Unset): None: every agent
     """

    agent: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        agent: None | str | Unset
        if isinstance(self.agent, Unset):
            agent = UNSET
        else:
            agent = self.agent


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if agent is not UNSET:
            field_dict["agent"] = agent

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


        resume_request = cls(
            agent=agent,
        )

        return resume_request

