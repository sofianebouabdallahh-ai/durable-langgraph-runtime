from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.client_error_kind import ClientErrorKind
from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ClientError")



@_attrs_define
class ClientError:
    """ 
        Attributes:
            kind (ClientErrorKind):
            message (str):
            failed_request_id (None | str | Unset): The X-Request-ID of the API call that failed
            route (None | str | Unset): e.g. #/activity
            stack (None | str | Unset):
            version (None | str | Unset):
     """

    kind: ClientErrorKind
    message: str
    failed_request_id: None | str | Unset = UNSET
    route: None | str | Unset = UNSET
    stack: None | str | Unset = UNSET
    version: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value

        message = self.message

        failed_request_id: None | str | Unset
        if isinstance(self.failed_request_id, Unset):
            failed_request_id = UNSET
        else:
            failed_request_id = self.failed_request_id

        route: None | str | Unset
        if isinstance(self.route, Unset):
            route = UNSET
        else:
            route = self.route

        stack: None | str | Unset
        if isinstance(self.stack, Unset):
            stack = UNSET
        else:
            stack = self.stack

        version: None | str | Unset
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "kind": kind,
            "message": message,
        })
        if failed_request_id is not UNSET:
            field_dict["failed_request_id"] = failed_request_id
        if route is not UNSET:
            field_dict["route"] = route
        if stack is not UNSET:
            field_dict["stack"] = stack
        if version is not UNSET:
            field_dict["version"] = version

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        kind = ClientErrorKind(d.pop("kind"))




        message = d.pop("message")

        def _parse_failed_request_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        failed_request_id = _parse_failed_request_id(d.pop("failed_request_id", UNSET))


        def _parse_route(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        route = _parse_route(d.pop("route", UNSET))


        def _parse_stack(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        stack = _parse_stack(d.pop("stack", UNSET))


        def _parse_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        version = _parse_version(d.pop("version", UNSET))


        client_error = cls(
            kind=kind,
            message=message,
            failed_request_id=failed_request_id,
            route=route,
            stack=stack,
            version=version,
        )


        client_error.additional_properties = d
        return client_error

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
