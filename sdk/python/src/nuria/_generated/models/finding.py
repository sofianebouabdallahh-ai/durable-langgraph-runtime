from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.finding_severity import FindingSeverity
from typing import cast






T = TypeVar("T", bound="Finding")



@_attrs_define
class Finding:
    """ 
        Attributes:
            check (str):
            message (str):
            severity (FindingSeverity):
            where (None | str):
     """

    check: str
    message: str
    severity: FindingSeverity
    where: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        check = self.check

        message = self.message

        severity = self.severity.value

        where: None | str
        where = self.where


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "check": check,
            "message": message,
            "severity": severity,
            "where": where,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        check = d.pop("check")

        message = d.pop("message")

        severity = FindingSeverity(d.pop("severity"))




        def _parse_where(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        where = _parse_where(d.pop("where"))


        finding = cls(
            check=check,
            message=message,
            severity=severity,
            where=where,
        )


        finding.additional_properties = d
        return finding

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
