from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.audit_row_after_type_0 import AuditRowAfterType0
  from ..models.audit_row_before_type_0 import AuditRowBeforeType0





T = TypeVar("T", bound="AuditRow")



@_attrs_define
class AuditRow:
    """ 
        Attributes:
            action (str): e.g. agent.published, kill_switch.on
            actor (str):
            after (AuditRowAfterType0 | None):
            at (datetime.datetime):
            before (AuditRowBeforeType0 | None):
            id (UUID):
            request_id (None | str):
            target_id (None | str):
            target_type (str):
            trace_id (None | str):
     """

    action: str
    actor: str
    after: AuditRowAfterType0 | None
    at: datetime.datetime
    before: AuditRowBeforeType0 | None
    id: UUID
    request_id: None | str
    target_id: None | str
    target_type: str
    trace_id: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.audit_row_after_type_0 import AuditRowAfterType0 # noqa: PLC0415
        from ..models.audit_row_before_type_0 import AuditRowBeforeType0 # noqa: PLC0415
        action = self.action

        actor = self.actor

        after: dict[str, Any] | None
        if isinstance(self.after, AuditRowAfterType0):
            after = self.after.to_dict()
        else:
            after = self.after

        at = self.at.isoformat()

        before: dict[str, Any] | None
        if isinstance(self.before, AuditRowBeforeType0):
            before = self.before.to_dict()
        else:
            before = self.before

        id = str(self.id)

        request_id: None | str
        request_id = self.request_id

        target_id: None | str
        target_id = self.target_id

        target_type = self.target_type

        trace_id: None | str
        trace_id = self.trace_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "action": action,
            "actor": actor,
            "after": after,
            "at": at,
            "before": before,
            "id": id,
            "request_id": request_id,
            "target_id": target_id,
            "target_type": target_type,
            "trace_id": trace_id,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.audit_row_after_type_0 import AuditRowAfterType0 # noqa: PLC0415
        from ..models.audit_row_before_type_0 import AuditRowBeforeType0 # noqa: PLC0415
        d = dict(src_dict)
        action = d.pop("action")

        actor = d.pop("actor")

        def _parse_after(data: object) -> AuditRowAfterType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                after_type_0 = AuditRowAfterType0.from_dict(data)



                return after_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuditRowAfterType0 | None, data)

        after = _parse_after(d.pop("after"))


        at = datetime.datetime.fromisoformat(d.pop("at"))




        def _parse_before(data: object) -> AuditRowBeforeType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                before_type_0 = AuditRowBeforeType0.from_dict(data)



                return before_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuditRowBeforeType0 | None, data)

        before = _parse_before(d.pop("before"))


        id = UUID(d.pop("id"))




        def _parse_request_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        request_id = _parse_request_id(d.pop("request_id"))


        def _parse_target_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        target_id = _parse_target_id(d.pop("target_id"))


        target_type = d.pop("target_type")

        def _parse_trace_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        trace_id = _parse_trace_id(d.pop("trace_id"))


        audit_row = cls(
            action=action,
            actor=actor,
            after=after,
            at=at,
            before=before,
            id=id,
            request_id=request_id,
            target_id=target_id,
            target_type=target_type,
            trace_id=trace_id,
        )


        audit_row.additional_properties = d
        return audit_row

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
