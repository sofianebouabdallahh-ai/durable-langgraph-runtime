from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.skill_detail_origin import SkillDetailOrigin
from ..models.skill_detail_trust import SkillDetailTrust
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.file_view import FileView
  from ..models.scan_view import ScanView
  from ..models.skill_detail_meta import SkillDetailMeta





T = TypeVar("T", bound="SkillDetail")



@_attrs_define
class SkillDetail:
    """ 
        Attributes:
            allowed_tools (list[str]): What it asks for; never granted by it
            approved (bool): A person has read exactly this version. With a clean scan, an Always-use skill is then plain
                text in the prompt; until then it's data
            description (str): What it does and when to use it
            files (list[FileView]):
            id (UUID):
            instructions (str):
            meta (SkillDetailMeta):
            name (str):
            origin (SkillDetailOrigin):
            scan (ScanView):
            tokens (int): About how long its instructions are
            trust (SkillDetailTrust):
            updated_at (datetime.datetime):
            used_by (list[str]): Agents whose draft or published version use it
            version (str): The current version's content hash
     """

    allowed_tools: list[str]
    approved: bool
    description: str
    files: list[FileView]
    id: UUID
    instructions: str
    meta: SkillDetailMeta
    name: str
    origin: SkillDetailOrigin
    scan: ScanView
    tokens: int
    trust: SkillDetailTrust
    updated_at: datetime.datetime
    used_by: list[str]
    version: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.file_view import FileView # noqa: PLC0415
        from ..models.scan_view import ScanView # noqa: PLC0415
        from ..models.skill_detail_meta import SkillDetailMeta # noqa: PLC0415
        allowed_tools = self.allowed_tools



        approved = self.approved

        description = self.description

        files = []
        for files_item_data in self.files:
            files_item = files_item_data.to_dict()
            files.append(files_item)



        id = str(self.id)

        instructions = self.instructions

        meta = self.meta.to_dict()

        name = self.name

        origin = self.origin.value

        scan = self.scan.to_dict()

        tokens = self.tokens

        trust = self.trust.value

        updated_at = self.updated_at.isoformat()

        used_by = self.used_by



        version = self.version


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "allowed_tools": allowed_tools,
            "approved": approved,
            "description": description,
            "files": files,
            "id": id,
            "instructions": instructions,
            "meta": meta,
            "name": name,
            "origin": origin,
            "scan": scan,
            "tokens": tokens,
            "trust": trust,
            "updated_at": updated_at,
            "used_by": used_by,
            "version": version,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.file_view import FileView # noqa: PLC0415
        from ..models.scan_view import ScanView # noqa: PLC0415
        from ..models.skill_detail_meta import SkillDetailMeta # noqa: PLC0415
        d = dict(src_dict)
        allowed_tools = cast(list[str], d.pop("allowed_tools"))


        approved = d.pop("approved")

        description = d.pop("description")

        files = []
        _files = d.pop("files")
        for files_item_data in (_files):
            files_item = FileView.from_dict(files_item_data)



            files.append(files_item)


        id = UUID(d.pop("id"))




        instructions = d.pop("instructions")

        meta = SkillDetailMeta.from_dict(d.pop("meta"))




        name = d.pop("name")

        origin = SkillDetailOrigin(d.pop("origin"))




        scan = ScanView.from_dict(d.pop("scan"))




        tokens = d.pop("tokens")

        trust = SkillDetailTrust(d.pop("trust"))




        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))




        used_by = cast(list[str], d.pop("used_by"))


        version = d.pop("version")

        skill_detail = cls(
            allowed_tools=allowed_tools,
            approved=approved,
            description=description,
            files=files,
            id=id,
            instructions=instructions,
            meta=meta,
            name=name,
            origin=origin,
            scan=scan,
            tokens=tokens,
            trust=trust,
            updated_at=updated_at,
            used_by=used_by,
            version=version,
        )


        skill_detail.additional_properties = d
        return skill_detail

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
