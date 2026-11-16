from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.edit_skill_files import EditSkillFiles





T = TypeVar("T", bound="EditSkill")



@_attrs_define
class EditSkill:
    """ 
        Attributes:
            description (None | str | Unset):
            files (EditSkillFiles | Unset): path → new text, or null to remove the file
            instructions (None | str | Unset):
     """

    description: None | str | Unset = UNSET
    files: EditSkillFiles | Unset = UNSET
    instructions: None | str | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.edit_skill_files import EditSkillFiles # noqa: PLC0415
        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        files: dict[str, Any] | Unset = UNSET
        if not isinstance(self.files, Unset):
            files = self.files.to_dict()

        instructions: None | str | Unset
        if isinstance(self.instructions, Unset):
            instructions = UNSET
        else:
            instructions = self.instructions


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if description is not UNSET:
            field_dict["description"] = description
        if files is not UNSET:
            field_dict["files"] = files
        if instructions is not UNSET:
            field_dict["instructions"] = instructions

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.edit_skill_files import EditSkillFiles # noqa: PLC0415
        d = dict(src_dict)
        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))


        _files = d.pop("files", UNSET)
        files: EditSkillFiles | Unset
        if isinstance(_files,  Unset):
            files = UNSET
        else:
            files = EditSkillFiles.from_dict(_files)




        def _parse_instructions(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        instructions = _parse_instructions(d.pop("instructions", UNSET))


        edit_skill = cls(
            description=description,
            files=files,
            instructions=instructions,
        )

        return edit_skill

