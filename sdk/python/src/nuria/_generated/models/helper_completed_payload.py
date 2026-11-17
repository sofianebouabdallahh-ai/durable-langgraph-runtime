from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.helper_result_status import HelperResultStatus
from ..models.helper_status import HelperStatus
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="HelperCompletedPayload")



@_attrs_define
class HelperCompletedPayload:
    """ 
        Attributes:
            agent (str):
            handle (UUID):
            reason (None | str):
            result_status (HelperResultStatus | None):
            status (HelperStatus): A helper's state (`subagents/store.py` Status).
     """

    agent: str
    handle: UUID
    reason: None | str
    result_status: HelperResultStatus | None
    status: HelperStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        handle = str(self.handle)

        reason: None | str
        reason = self.reason

        result_status: None | str
        if isinstance(self.result_status, HelperResultStatus):
            result_status = self.result_status.value
        else:
            result_status = self.result_status

        status = self.status.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "handle": handle,
            "reason": reason,
            "result_status": result_status,
            "status": status,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        handle = UUID(d.pop("handle"))




        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))


        def _parse_result_status(data: object) -> HelperResultStatus | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                result_status_type_0 = HelperResultStatus(data)



                return result_status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(HelperResultStatus | None, data)

        result_status = _parse_result_status(d.pop("result_status"))


        status = HelperStatus(d.pop("status"))




        helper_completed_payload = cls(
            agent=agent,
            handle=handle,
            reason=reason,
            result_status=result_status,
            status=status,
        )


        helper_completed_payload.additional_properties = d
        return helper_completed_payload

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
