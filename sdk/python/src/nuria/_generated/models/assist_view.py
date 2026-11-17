from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.assist_view_kind import AssistViewKind
from ..models.assist_view_status import AssistViewStatus
from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.assist_view_proposal_type_0 import AssistViewProposalType0





T = TypeVar("T", bound="AssistView")



@_attrs_define
class AssistView:
    """ 
        Attributes:
            kind (AssistViewKind):
            problem (None | str): Why there's no proposal, in plain words
            proposal (AssistViewProposalType0 | None): A DraftProposal or an InstructionsProposal, when done
            status (AssistViewStatus):
            repairs (list[str] | Unset): What was fixed in the draft
     """

    kind: AssistViewKind
    problem: None | str
    proposal: AssistViewProposalType0 | None
    status: AssistViewStatus
    repairs: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.assist_view_proposal_type_0 import AssistViewProposalType0 # noqa: PLC0415
        kind = self.kind.value

        problem: None | str
        problem = self.problem

        proposal: dict[str, Any] | None
        if isinstance(self.proposal, AssistViewProposalType0):
            proposal = self.proposal.to_dict()
        else:
            proposal = self.proposal

        status = self.status.value

        repairs: list[str] | Unset = UNSET
        if not isinstance(self.repairs, Unset):
            repairs = self.repairs




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "kind": kind,
            "problem": problem,
            "proposal": proposal,
            "status": status,
        })
        if repairs is not UNSET:
            field_dict["repairs"] = repairs

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.assist_view_proposal_type_0 import AssistViewProposalType0 # noqa: PLC0415
        d = dict(src_dict)
        kind = AssistViewKind(d.pop("kind"))




        def _parse_problem(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        problem = _parse_problem(d.pop("problem"))


        def _parse_proposal(data: object) -> AssistViewProposalType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                proposal_type_0 = AssistViewProposalType0.from_dict(data)



                return proposal_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AssistViewProposalType0 | None, data)

        proposal = _parse_proposal(d.pop("proposal"))


        status = AssistViewStatus(d.pop("status"))




        repairs = cast(list[str], d.pop("repairs", UNSET))


        assist_view = cls(
            kind=kind,
            problem=problem,
            proposal=proposal,
            status=status,
            repairs=repairs,
        )


        assist_view.additional_properties = d
        return assist_view

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
