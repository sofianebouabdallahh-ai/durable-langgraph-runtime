from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.connection_view import ConnectionView





T = TypeVar("T", bound="DefaultView")



@_attrs_define
class DefaultView:
    """ 
        Attributes:
            connection (ConnectionView | None):
            model (None | str):
            setup_provider (str): What roles use when no default is set
     """

    connection: ConnectionView | None
    model: None | str
    setup_provider: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.connection_view import ConnectionView # noqa: PLC0415
        connection: dict[str, Any] | None
        if isinstance(self.connection, ConnectionView):
            connection = self.connection.to_dict()
        else:
            connection = self.connection

        model: None | str
        model = self.model

        setup_provider = self.setup_provider


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "connection": connection,
            "model": model,
            "setup_provider": setup_provider,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connection_view import ConnectionView # noqa: PLC0415
        d = dict(src_dict)
        def _parse_connection(data: object) -> ConnectionView | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                connection_type_0 = ConnectionView.from_dict(data)



                return connection_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ConnectionView | None, data)

        connection = _parse_connection(d.pop("connection"))


        def _parse_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        model = _parse_model(d.pop("model"))


        setup_provider = d.pop("setup_provider")

        default_view = cls(
            connection=connection,
            model=model,
            setup_provider=setup_provider,
        )


        default_view.additional_properties = d
        return default_view

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
