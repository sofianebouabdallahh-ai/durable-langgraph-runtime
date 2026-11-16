from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.approval_request_decision import ApprovalRequestDecision
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.approval_edits import ApprovalEdits





T = TypeVar("T", bound="ApprovalRequest")



@_attrs_define
class ApprovalRequest:
    """ R1.4: `{approval_id?, decision: approve|reject, edits?, reason?}`.

        Attributes:
            decision (ApprovalRequestDecision):
            approval_id (None | Unset | UUID): Which approval this decides (`interrupt_payload.approval_id`). Send it: it
                makes sure you decide the call you were shown. Without it, the request applies only when exactly one approval is
                pending (409 otherwise).
            edits (ApprovalEdits | None | Unset):
            reason (None | str | Unset):
     """

    decision: ApprovalRequestDecision
    approval_id: None | Unset | UUID = UNSET
    edits: ApprovalEdits | None | Unset = UNSET
    reason: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.approval_edits import ApprovalEdits # noqa: PLC0415
        decision = self.decision.value

        approval_id: None | str | Unset
        if isinstance(self.approval_id, Unset):
            approval_id = UNSET
        elif isinstance(self.approval_id, UUID):
            approval_id = str(self.approval_id)
        else:
            approval_id = self.approval_id

        edits: dict[str, Any] | None | Unset
        if isinstance(self.edits, Unset):
            edits = UNSET
        elif isinstance(self.edits, ApprovalEdits):
            edits = self.edits.to_dict()
        else:
            edits = self.edits

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "decision": decision,
        })
        if approval_id is not UNSET:
            field_dict["approval_id"] = approval_id
        if edits is not UNSET:
            field_dict["edits"] = edits
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.approval_edits import ApprovalEdits # noqa: PLC0415
        d = dict(src_dict)
        decision = ApprovalRequestDecision(d.pop("decision"))




        def _parse_approval_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                approval_id_type_0 = UUID(data)



                return approval_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        approval_id = _parse_approval_id(d.pop("approval_id", UNSET))


        def _parse_edits(data: object) -> ApprovalEdits | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                edits_type_0 = ApprovalEdits.from_dict(data)



                return edits_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ApprovalEdits | None | Unset, data)

        edits = _parse_edits(d.pop("edits", UNSET))


        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))


        approval_request = cls(
            decision=decision,
            approval_id=approval_id,
            edits=edits,
            reason=reason,
        )

        return approval_request

