from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.mcp_tool_view import McpToolView





T = TypeVar("T", bound="McpServerView")



@_attrs_define
class McpServerView:
    """ 
        Attributes:
            display_name (str):
            has_token (bool):
            header_name (str):
            id (UUID):
            name (str):
            protocol_version (None | str):
            status (str): untested, ready or failed
            status_detail (None | str):
            tested_at (datetime.datetime | None):
            token_fingerprint (None | str):
            tools (list[McpToolView]):
            url (str):
     """

    display_name: str
    has_token: bool
    header_name: str
    id: UUID
    name: str
    protocol_version: None | str
    status: str
    status_detail: None | str
    tested_at: datetime.datetime | None
    token_fingerprint: None | str
    tools: list[McpToolView]
    url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.mcp_tool_view import McpToolView # noqa: PLC0415
        display_name = self.display_name

        has_token = self.has_token

        header_name = self.header_name

        id = str(self.id)

        name = self.name

        protocol_version: None | str
        protocol_version = self.protocol_version

        status = self.status

        status_detail: None | str
        status_detail = self.status_detail

        tested_at: None | str
        if isinstance(self.tested_at, datetime.datetime):
            tested_at = self.tested_at.isoformat()
        else:
            tested_at = self.tested_at

        token_fingerprint: None | str
        token_fingerprint = self.token_fingerprint

        tools = []
        for tools_item_data in self.tools:
            tools_item = tools_item_data.to_dict()
            tools.append(tools_item)



        url = self.url


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "display_name": display_name,
            "has_token": has_token,
            "header_name": header_name,
            "id": id,
            "name": name,
            "protocol_version": protocol_version,
            "status": status,
            "status_detail": status_detail,
            "tested_at": tested_at,
            "token_fingerprint": token_fingerprint,
            "tools": tools,
            "url": url,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.mcp_tool_view import McpToolView # noqa: PLC0415
        d = dict(src_dict)
        display_name = d.pop("display_name")

        has_token = d.pop("has_token")

        header_name = d.pop("header_name")

        id = UUID(d.pop("id"))




        name = d.pop("name")

        def _parse_protocol_version(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        protocol_version = _parse_protocol_version(d.pop("protocol_version"))


        status = d.pop("status")

        def _parse_status_detail(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        status_detail = _parse_status_detail(d.pop("status_detail"))


        def _parse_tested_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                tested_at_type_0 = datetime.datetime.fromisoformat(data)



                return tested_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        tested_at = _parse_tested_at(d.pop("tested_at"))


        def _parse_token_fingerprint(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        token_fingerprint = _parse_token_fingerprint(d.pop("token_fingerprint"))


        tools = []
        _tools = d.pop("tools")
        for tools_item_data in (_tools):
            tools_item = McpToolView.from_dict(tools_item_data)



            tools.append(tools_item)


        url = d.pop("url")

        mcp_server_view = cls(
            display_name=display_name,
            has_token=has_token,
            header_name=header_name,
            id=id,
            name=name,
            protocol_version=protocol_version,
            status=status,
            status_detail=status_detail,
            tested_at=tested_at,
            token_fingerprint=token_fingerprint,
            tools=tools,
            url=url,
        )


        mcp_server_view.additional_properties = d
        return mcp_server_view

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
