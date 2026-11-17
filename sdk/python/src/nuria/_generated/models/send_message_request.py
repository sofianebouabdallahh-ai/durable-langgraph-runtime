from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.send_message_request_options_type_0 import SendMessageRequestOptionsType0
  from ..models.send_message_request_script_type_0_item import SendMessageRequestScriptType0Item
  from ..models.send_message_request_subagent_scripts_type_0 import SendMessageRequestSubagentScriptsType0





T = TypeVar("T", bound="SendMessageRequest")



@_attrs_define
class SendMessageRequest:
    """ 
        Attributes:
            content (str):
            options (None | SendMessageRequestOptionsType0 | Unset):
            script (list[SendMessageRequestScriptType0Item] | None | Unset):
            subagent_scripts (None | SendMessageRequestSubagentScriptsType0 | Unset):
     """

    content: str
    options: None | SendMessageRequestOptionsType0 | Unset = UNSET
    script: list[SendMessageRequestScriptType0Item] | None | Unset = UNSET
    subagent_scripts: None | SendMessageRequestSubagentScriptsType0 | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.send_message_request_options_type_0 import SendMessageRequestOptionsType0 # noqa: PLC0415
        from ..models.send_message_request_script_type_0_item import SendMessageRequestScriptType0Item # noqa: PLC0415
        from ..models.send_message_request_subagent_scripts_type_0 import SendMessageRequestSubagentScriptsType0 # noqa: PLC0415
        content = self.content

        options: dict[str, Any] | None | Unset
        if isinstance(self.options, Unset):
            options = UNSET
        elif isinstance(self.options, SendMessageRequestOptionsType0):
            options = self.options.to_dict()
        else:
            options = self.options

        script: list[dict[str, Any]] | None | Unset
        if isinstance(self.script, Unset):
            script = UNSET
        elif isinstance(self.script, list):
            script = []
            for script_type_0_item_data in self.script:
                script_type_0_item = script_type_0_item_data.to_dict()
                script.append(script_type_0_item)


        else:
            script = self.script

        subagent_scripts: dict[str, Any] | None | Unset
        if isinstance(self.subagent_scripts, Unset):
            subagent_scripts = UNSET
        elif isinstance(self.subagent_scripts, SendMessageRequestSubagentScriptsType0):
            subagent_scripts = self.subagent_scripts.to_dict()
        else:
            subagent_scripts = self.subagent_scripts


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "content": content,
        })
        if options is not UNSET:
            field_dict["options"] = options
        if script is not UNSET:
            field_dict["script"] = script
        if subagent_scripts is not UNSET:
            field_dict["subagent_scripts"] = subagent_scripts

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.send_message_request_options_type_0 import SendMessageRequestOptionsType0 # noqa: PLC0415
        from ..models.send_message_request_script_type_0_item import SendMessageRequestScriptType0Item # noqa: PLC0415
        from ..models.send_message_request_subagent_scripts_type_0 import SendMessageRequestSubagentScriptsType0 # noqa: PLC0415
        d = dict(src_dict)
        content = d.pop("content")

        def _parse_options(data: object) -> None | SendMessageRequestOptionsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                options_type_0 = SendMessageRequestOptionsType0.from_dict(data)



                return options_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SendMessageRequestOptionsType0 | Unset, data)

        options = _parse_options(d.pop("options", UNSET))


        def _parse_script(data: object) -> list[SendMessageRequestScriptType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                script_type_0 = []
                _script_type_0 = data
                for script_type_0_item_data in (_script_type_0):
                    script_type_0_item = SendMessageRequestScriptType0Item.from_dict(script_type_0_item_data)



                    script_type_0.append(script_type_0_item)

                return script_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[SendMessageRequestScriptType0Item] | None | Unset, data)

        script = _parse_script(d.pop("script", UNSET))


        def _parse_subagent_scripts(data: object) -> None | SendMessageRequestSubagentScriptsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                subagent_scripts_type_0 = SendMessageRequestSubagentScriptsType0.from_dict(data)



                return subagent_scripts_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SendMessageRequestSubagentScriptsType0 | Unset, data)

        subagent_scripts = _parse_subagent_scripts(d.pop("subagent_scripts", UNSET))


        send_message_request = cls(
            content=content,
            options=options,
            script=script,
            subagent_scripts=subagent_scripts,
        )

        return send_message_request

