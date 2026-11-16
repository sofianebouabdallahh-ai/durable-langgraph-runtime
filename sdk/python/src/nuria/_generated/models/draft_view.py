from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.agent_document import AgentDocument
  from ..models.issue_view import IssueView





T = TypeVar("T", bound="DraftView")



@_attrs_define
class DraftView:
    """ 
        Attributes:
            blockers (list[str]): What stands between this draft and publishing
            document (AgentDocument):
            issues (list[IssueView]):
            number (int):
            tested (bool): A test-chat reply completed on exactly this draft
            skills_unread (list[str] | Unset): Skills it uses that nobody has read yet (H10): data in prompts until approved
                on the Skills page. Not a blocker
            tests (int | Unset): Its test cases (H6): with any, they're the gate Default: 0.
            tests_failing (list[str] | Unset): Cases not passed on exactly this draft
     """

    blockers: list[str]
    document: AgentDocument
    issues: list[IssueView]
    number: int
    tested: bool
    skills_unread: list[str] | Unset = UNSET
    tests: int | Unset = 0
    tests_failing: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_document import AgentDocument # noqa: PLC0415
        from ..models.issue_view import IssueView # noqa: PLC0415
        blockers = self.blockers



        document = self.document.to_dict()

        issues = []
        for issues_item_data in self.issues:
            issues_item = issues_item_data.to_dict()
            issues.append(issues_item)



        number = self.number

        tested = self.tested

        skills_unread: list[str] | Unset = UNSET
        if not isinstance(self.skills_unread, Unset):
            skills_unread = self.skills_unread



        tests = self.tests

        tests_failing: list[str] | Unset = UNSET
        if not isinstance(self.tests_failing, Unset):
            tests_failing = self.tests_failing




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "blockers": blockers,
            "document": document,
            "issues": issues,
            "number": number,
            "tested": tested,
        })
        if skills_unread is not UNSET:
            field_dict["skills_unread"] = skills_unread
        if tests is not UNSET:
            field_dict["tests"] = tests
        if tests_failing is not UNSET:
            field_dict["tests_failing"] = tests_failing

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_document import AgentDocument # noqa: PLC0415
        from ..models.issue_view import IssueView # noqa: PLC0415
        d = dict(src_dict)
        blockers = cast(list[str], d.pop("blockers"))


        document = AgentDocument.from_dict(d.pop("document"))




        issues = []
        _issues = d.pop("issues")
        for issues_item_data in (_issues):
            issues_item = IssueView.from_dict(issues_item_data)



            issues.append(issues_item)


        number = d.pop("number")

        tested = d.pop("tested")

        skills_unread = cast(list[str], d.pop("skills_unread", UNSET))


        tests = d.pop("tests", UNSET)

        tests_failing = cast(list[str], d.pop("tests_failing", UNSET))


        draft_view = cls(
            blockers=blockers,
            document=document,
            issues=issues,
            number=number,
            tested=tested,
            skills_unread=skills_unread,
            tests=tests,
            tests_failing=tests_failing,
        )


        draft_view.additional_properties = d
        return draft_view

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
