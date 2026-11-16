from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.case_subagent_scripts import CaseSubagentScripts
  from ..models.expect import Expect
  from ..models.script_turn import ScriptTurn





T = TypeVar("T", bound="Case")



@_attrs_define
class Case:
    """ 
        Attributes:
            message (str):
            name (str):
            approve (bool | Unset): the test's answer when the agent asks Default: True.
            expect (Expect | Unset): What the turn must do. Every field set is one check; none set: it completed.
            script (list[ScriptTurn] | Unset):
            subagent_scripts (CaseSubagentScripts | Unset):
     """

    message: str
    name: str
    approve: bool | Unset = True
    expect: Expect | Unset = UNSET
    script: list[ScriptTurn] | Unset = UNSET
    subagent_scripts: CaseSubagentScripts | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.case_subagent_scripts import CaseSubagentScripts # noqa: PLC0415
        from ..models.expect import Expect # noqa: PLC0415
        from ..models.script_turn import ScriptTurn # noqa: PLC0415
        message = self.message

        name = self.name

        approve = self.approve

        expect: dict[str, Any] | Unset = UNSET
        if not isinstance(self.expect, Unset):
            expect = self.expect.to_dict()

        script: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.script, Unset):
            script = []
            for script_item_data in self.script:
                script_item = script_item_data.to_dict()
                script.append(script_item)



        subagent_scripts: dict[str, Any] | Unset = UNSET
        if not isinstance(self.subagent_scripts, Unset):
            subagent_scripts = self.subagent_scripts.to_dict()


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "message": message,
            "name": name,
        })
        if approve is not UNSET:
            field_dict["approve"] = approve
        if expect is not UNSET:
            field_dict["expect"] = expect
        if script is not UNSET:
            field_dict["script"] = script
        if subagent_scripts is not UNSET:
            field_dict["subagent_scripts"] = subagent_scripts

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.case_subagent_scripts import CaseSubagentScripts # noqa: PLC0415
        from ..models.expect import Expect # noqa: PLC0415
        from ..models.script_turn import ScriptTurn # noqa: PLC0415
        d = dict(src_dict)
        message = d.pop("message")

        name = d.pop("name")

        approve = d.pop("approve", UNSET)

        _expect = d.pop("expect", UNSET)
        expect: Expect | Unset
        if isinstance(_expect,  Unset):
            expect = UNSET
        else:
            expect = Expect.from_dict(_expect)




        _script = d.pop("script", UNSET)
        script: list[ScriptTurn] | Unset = UNSET
        if _script is not UNSET:
            script = []
            for script_item_data in _script:
                script_item = ScriptTurn.from_dict(script_item_data)



                script.append(script_item)


        _subagent_scripts = d.pop("subagent_scripts", UNSET)
        subagent_scripts: CaseSubagentScripts | Unset
        if isinstance(_subagent_scripts,  Unset):
            subagent_scripts = UNSET
        else:
            subagent_scripts = CaseSubagentScripts.from_dict(_subagent_scripts)




        case = cls(
            message=message,
            name=name,
            approve=approve,
            expect=expect,
            script=script,
            subagent_scripts=subagent_scripts,
        )

        return case

