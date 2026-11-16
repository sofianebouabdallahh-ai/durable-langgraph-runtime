from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.scan_view_status import ScanViewStatus
from typing import cast

if TYPE_CHECKING:
  from ..models.finding import Finding





T = TypeVar("T", bound="ScanView")



@_attrs_define
class ScanView:
    """ 
        Attributes:
            findings (list[Finding]):
            status (ScanViewStatus):
     """

    findings: list[Finding]
    status: ScanViewStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.finding import Finding # noqa: PLC0415
        findings = []
        for findings_item_data in self.findings:
            findings_item = findings_item_data.to_dict()
            findings.append(findings_item)



        status = self.status.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "findings": findings,
            "status": status,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.finding import Finding # noqa: PLC0415
        d = dict(src_dict)
        findings = []
        _findings = d.pop("findings")
        for findings_item_data in (_findings):
            findings_item = Finding.from_dict(findings_item_data)



            findings.append(findings_item)


        status = ScanViewStatus(d.pop("status"))




        scan_view = cls(
            findings=findings,
            status=status,
        )


        scan_view.additional_properties = d
        return scan_view

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
