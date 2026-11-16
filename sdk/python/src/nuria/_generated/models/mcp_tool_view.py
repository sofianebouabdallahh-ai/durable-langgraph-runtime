from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.mcp_tool_view_hints import McpToolViewHints
  from ..models.mcp_tool_view_input_schema import McpToolViewInputSchema
  from ..models.mcp_tool_view_scan import McpToolViewScan





T = TypeVar("T", bound="McpToolView")



@_attrs_define
class McpToolView:
    """ 
        Attributes:
            agent_name (str): As agents know it: mcp__<server>__<tool>
            approved_description (None | str): What was switched on, if different
            changed (bool): The server changed it since it was switched on
            description (str): What the server says now
            enabled (bool):
            hints (McpToolViewHints):
            input_schema (McpToolViewInputSchema):
            name (str): As the server names it
            read_only (bool): The server says so (a hint, never trusted alone)
            scan (McpToolViewScan): The check of its description and arguments
            without_asking (bool):
     """

    agent_name: str
    approved_description: None | str
    changed: bool
    description: str
    enabled: bool
    hints: McpToolViewHints
    input_schema: McpToolViewInputSchema
    name: str
    read_only: bool
    scan: McpToolViewScan
    without_asking: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.mcp_tool_view_hints import McpToolViewHints # noqa: PLC0415
        from ..models.mcp_tool_view_input_schema import McpToolViewInputSchema # noqa: PLC0415
        from ..models.mcp_tool_view_scan import McpToolViewScan # noqa: PLC0415
        agent_name = self.agent_name

        approved_description: None | str
        approved_description = self.approved_description

        changed = self.changed

        description = self.description

        enabled = self.enabled

        hints = self.hints.to_dict()

        input_schema = self.input_schema.to_dict()

        name = self.name

        read_only = self.read_only

        scan = self.scan.to_dict()

        without_asking = self.without_asking


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent_name": agent_name,
            "approved_description": approved_description,
            "changed": changed,
            "description": description,
            "enabled": enabled,
            "hints": hints,
            "input_schema": input_schema,
            "name": name,
            "read_only": read_only,
            "scan": scan,
            "without_asking": without_asking,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.mcp_tool_view_hints import McpToolViewHints # noqa: PLC0415
        from ..models.mcp_tool_view_input_schema import McpToolViewInputSchema # noqa: PLC0415
        from ..models.mcp_tool_view_scan import McpToolViewScan # noqa: PLC0415
        d = dict(src_dict)
        agent_name = d.pop("agent_name")

        def _parse_approved_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        approved_description = _parse_approved_description(d.pop("approved_description"))


        changed = d.pop("changed")

        description = d.pop("description")

        enabled = d.pop("enabled")

        hints = McpToolViewHints.from_dict(d.pop("hints"))




        input_schema = McpToolViewInputSchema.from_dict(d.pop("input_schema"))




        name = d.pop("name")

        read_only = d.pop("read_only")

        scan = McpToolViewScan.from_dict(d.pop("scan"))




        without_asking = d.pop("without_asking")

        mcp_tool_view = cls(
            agent_name=agent_name,
            approved_description=approved_description,
            changed=changed,
            description=description,
            enabled=enabled,
            hints=hints,
            input_schema=input_schema,
            name=name,
            read_only=read_only,
            scan=scan,
            without_asking=without_asking,
        )


        mcp_tool_view.additional_properties = d
        return mcp_tool_view

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
