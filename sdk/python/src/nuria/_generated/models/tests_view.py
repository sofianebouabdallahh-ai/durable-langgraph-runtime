from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.case_view import CaseView





T = TypeVar("T", bound="TestsView")



@_attrs_define
class TestsView:
    """ 
        Attributes:
            blocking (bool): Publishing waits for these tests
            cases (list[CaseView]):
            passing (int): Cases passed on this draft, as they are now
     """

    blocking: bool
    cases: list[CaseView]
    passing: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.case_view import CaseView # noqa: PLC0415
        blocking = self.blocking

        cases = []
        for cases_item_data in self.cases:
            cases_item = cases_item_data.to_dict()
            cases.append(cases_item)



        passing = self.passing


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "blocking": blocking,
            "cases": cases,
            "passing": passing,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.case_view import CaseView # noqa: PLC0415
        d = dict(src_dict)
        blocking = d.pop("blocking")

        cases = []
        _cases = d.pop("cases")
        for cases_item_data in (_cases):
            cases_item = CaseView.from_dict(cases_item_data)



            cases.append(cases_item)


        passing = d.pop("passing")

        tests_view = cls(
            blocking=blocking,
            cases=cases,
            passing=passing,
        )


        tests_view.additional_properties = d
        return tests_view

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
