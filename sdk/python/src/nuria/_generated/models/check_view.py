from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="CheckView")



@_attrs_define
class CheckView:
    """ 
        Attributes:
            check (str):
            ok (bool):
            detail (str | Unset):  Default: ''.
            error (bool | Unset):  Default: False.
     """

    check: str
    ok: bool
    detail: str | Unset = ''
    error: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        check = self.check

        ok = self.ok

        detail = self.detail

        error = self.error


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "check": check,
            "ok": ok,
        })
        if detail is not UNSET:
            field_dict["detail"] = detail
        if error is not UNSET:
            field_dict["error"] = error

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        check = d.pop("check")

        ok = d.pop("ok")

        detail = d.pop("detail", UNSET)

        error = d.pop("error", UNSET)

        check_view = cls(
            check=check,
            ok=ok,
            detail=detail,
            error=error,
        )


        check_view.additional_properties = d
        return check_view

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
