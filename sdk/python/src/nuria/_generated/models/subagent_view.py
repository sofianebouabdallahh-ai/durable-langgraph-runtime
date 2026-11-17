from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.subagent_view_result_type_0 import SubagentViewResultType0
  from ..models.subagent_view_usage import SubagentViewUsage





T = TypeVar("T", bound="SubagentView")



@_attrs_define
class SubagentView:
    """ 
        Attributes:
            agent (str):
            elapsed_s (float):
            handle (UUID):
            percent (int | None):
            progress (None | str): The latest report_progress message
            result (None | SubagentViewResultType0):
            status (str):
            usage (SubagentViewUsage):
     """

    agent: str
    elapsed_s: float
    handle: UUID
    percent: int | None
    progress: None | str
    result: None | SubagentViewResultType0
    status: str
    usage: SubagentViewUsage
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.subagent_view_result_type_0 import SubagentViewResultType0 # noqa: PLC0415
        from ..models.subagent_view_usage import SubagentViewUsage # noqa: PLC0415
        agent = self.agent

        elapsed_s = self.elapsed_s

        handle = str(self.handle)

        percent: int | None
        percent = self.percent

        progress: None | str
        progress = self.progress

        result: dict[str, Any] | None
        if isinstance(self.result, SubagentViewResultType0):
            result = self.result.to_dict()
        else:
            result = self.result

        status = self.status

        usage = self.usage.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "elapsed_s": elapsed_s,
            "handle": handle,
            "percent": percent,
            "progress": progress,
            "result": result,
            "status": status,
            "usage": usage,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.subagent_view_result_type_0 import SubagentViewResultType0 # noqa: PLC0415
        from ..models.subagent_view_usage import SubagentViewUsage # noqa: PLC0415
        d = dict(src_dict)
        agent = d.pop("agent")

        elapsed_s = d.pop("elapsed_s")

        handle = UUID(d.pop("handle"))




        def _parse_percent(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        percent = _parse_percent(d.pop("percent"))


        def _parse_progress(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        progress = _parse_progress(d.pop("progress"))


        def _parse_result(data: object) -> None | SubagentViewResultType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_0 = SubagentViewResultType0.from_dict(data)



                return result_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SubagentViewResultType0, data)

        result = _parse_result(d.pop("result"))


        status = d.pop("status")

        usage = SubagentViewUsage.from_dict(d.pop("usage"))




        subagent_view = cls(
            agent=agent,
            elapsed_s=elapsed_s,
            handle=handle,
            percent=percent,
            progress=progress,
            result=result,
            status=status,
            usage=usage,
        )


        subagent_view.additional_properties = d
        return subagent_view

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
