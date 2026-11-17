from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="IssueView")



@_attrs_define
class IssueView:
    """ 
        Attributes:
            field (None | str):
            message (str):
            where (str): 'agent' or 'helpers.<name>'
     """

    field: None | str
    message: str
    where: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        field: None | str
        field = self.field

        message = self.message

        where = self.where


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "field": field,
            "message": message,
            "where": where,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_field(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        field = _parse_field(d.pop("field"))


        message = d.pop("message")

        where = d.pop("where")

        issue_view = cls(
            field=field,
            message=message,
            where=where,
        )


        issue_view.additional_properties = d
        return issue_view

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
