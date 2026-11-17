from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.connection_view import ConnectionView





T = TypeVar("T", bound="TestView")



@_attrs_define
class TestView:
    """ 
        Attributes:
            connection (ConnectionView):
            detail (str):
            model (str):
            ok (bool):
            seconds (float):
     """

    connection: ConnectionView
    detail: str
    model: str
    ok: bool
    seconds: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.connection_view import ConnectionView # noqa: PLC0415
        connection = self.connection.to_dict()

        detail = self.detail

        model = self.model

        ok = self.ok

        seconds = self.seconds


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "connection": connection,
            "detail": detail,
            "model": model,
            "ok": ok,
            "seconds": seconds,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connection_view import ConnectionView # noqa: PLC0415
        d = dict(src_dict)
        connection = ConnectionView.from_dict(d.pop("connection"))




        detail = d.pop("detail")

        model = d.pop("model")

        ok = d.pop("ok")

        seconds = d.pop("seconds")

        test_view = cls(
            connection=connection,
            detail=detail,
            model=model,
            ok=ok,
            seconds=seconds,
        )


        test_view.additional_properties = d
        return test_view

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
