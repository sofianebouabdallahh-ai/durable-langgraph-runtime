from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.new_skill_files import NewSkillFiles





T = TypeVar("T", bound="NewSkill")



@_attrs_define
class NewSkill:
    """ 
        Attributes:
            description (str):
            instructions (str):
            name (str):
            files (NewSkillFiles | Unset): Reference files typed in the form: path → text
     """

    description: str
    instructions: str
    name: str
    files: NewSkillFiles | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.new_skill_files import NewSkillFiles # noqa: PLC0415
        description = self.description

        instructions = self.instructions

        name = self.name

        files: dict[str, Any] | Unset = UNSET
        if not isinstance(self.files, Unset):
            files = self.files.to_dict()


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "description": description,
            "instructions": instructions,
            "name": name,
        })
        if files is not UNSET:
            field_dict["files"] = files

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.new_skill_files import NewSkillFiles # noqa: PLC0415
        d = dict(src_dict)
        description = d.pop("description")

        instructions = d.pop("instructions")

        name = d.pop("name")

        _files = d.pop("files", UNSET)
        files: NewSkillFiles | Unset
        if isinstance(_files,  Unset):
            files = UNSET
        else:
            files = NewSkillFiles.from_dict(_files)




        new_skill = cls(
            description=description,
            instructions=instructions,
            name=name,
            files=files,
        )

        return new_skill

