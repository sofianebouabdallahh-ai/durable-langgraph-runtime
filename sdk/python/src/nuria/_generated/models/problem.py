from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="Problem")



@_attrs_define
class Problem:
    """ An error, as RFC 9457 problem details. Branch on `type`; a problem may carry more
    fields of its own (`run_id`, `limit`, `agent`, ...).

        Attributes:
            detail (str): This occurrence, in words for a person
            status (int): The HTTP status code
            title (str): A short summary of the kind of problem
            type_ (str): A URI naming the kind of problem: the field to branch on
     """

    detail: str
    status: int
    title: str
    type_: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        detail = self.detail

        status = self.status

        title = self.title

        type_ = self.type_


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "detail": detail,
            "status": status,
            "title": title,
            "type": type_,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        detail = d.pop("detail")

        status = d.pop("status")

        title = d.pop("title")

        type_ = d.pop("type")

        problem = cls(
            detail=detail,
            status=status,
            title=title,
            type_=type_,
        )


        problem.additional_properties = d
        return problem

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
