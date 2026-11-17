from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.scripted_tool_call import ScriptedToolCall





T = TypeVar("T", bound="ScriptTurn")



@_attrs_define
class ScriptTurn:
    """ One model reply: text, tool calls, or both.

        Attributes:
            content (str | Unset):  Default: ''.
            tool_calls (list[ScriptedToolCall] | Unset):
     """

    content: str | Unset = ''
    tool_calls: list[ScriptedToolCall] | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.scripted_tool_call import ScriptedToolCall # noqa: PLC0415
        content = self.content

        tool_calls: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.tool_calls, Unset):
            tool_calls = []
            for tool_calls_item_data in self.tool_calls:
                tool_calls_item = tool_calls_item_data.to_dict()
                tool_calls.append(tool_calls_item)




        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if content is not UNSET:
            field_dict["content"] = content
        if tool_calls is not UNSET:
            field_dict["tool_calls"] = tool_calls

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.scripted_tool_call import ScriptedToolCall # noqa: PLC0415
        d = dict(src_dict)
        content = d.pop("content", UNSET)

        _tool_calls = d.pop("tool_calls", UNSET)
        tool_calls: list[ScriptedToolCall] | Unset = UNSET
        if _tool_calls is not UNSET:
            tool_calls = []
            for tool_calls_item_data in _tool_calls:
                tool_calls_item = ScriptedToolCall.from_dict(tool_calls_item_data)



                tool_calls.append(tool_calls_item)


        script_turn = cls(
            content=content,
            tool_calls=tool_calls,
        )

        return script_turn

