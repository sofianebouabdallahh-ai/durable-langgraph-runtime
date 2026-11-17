from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.studio_agent_view_status import StudioAgentViewStatus
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.agent_document import AgentDocument
  from ..models.draft_view import DraftView
  from ..models.version_view import VersionView





T = TypeVar("T", bound="StudioAgentView")



@_attrs_define
class StudioAgentView:
    """ 
        Attributes:
            archived (bool):
            description (str):
            display_name (str):
            draft (DraftView | None):
            id (UUID):
            name (str):
            published (None | VersionView):
            published_document (AgentDocument | None):
            status (StudioAgentViewStatus): Never published / published, nothing pending / published, with a draft
            versions (list[VersionView]):
     """

    archived: bool
    description: str
    display_name: str
    draft: DraftView | None
    id: UUID
    name: str
    published: None | VersionView
    published_document: AgentDocument | None
    status: StudioAgentViewStatus
    versions: list[VersionView]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_document import AgentDocument # noqa: PLC0415
        from ..models.draft_view import DraftView # noqa: PLC0415
        from ..models.version_view import VersionView # noqa: PLC0415
        archived = self.archived

        description = self.description

        display_name = self.display_name

        draft: dict[str, Any] | None
        if isinstance(self.draft, DraftView):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        id = str(self.id)

        name = self.name

        published: dict[str, Any] | None
        if isinstance(self.published, VersionView):
            published = self.published.to_dict()
        else:
            published = self.published

        published_document: dict[str, Any] | None
        if isinstance(self.published_document, AgentDocument):
            published_document = self.published_document.to_dict()
        else:
            published_document = self.published_document

        status = self.status.value

        versions = []
        for versions_item_data in self.versions:
            versions_item = versions_item_data.to_dict()
            versions.append(versions_item)




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "archived": archived,
            "description": description,
            "display_name": display_name,
            "draft": draft,
            "id": id,
            "name": name,
            "published": published,
            "published_document": published_document,
            "status": status,
            "versions": versions,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_document import AgentDocument # noqa: PLC0415
        from ..models.draft_view import DraftView # noqa: PLC0415
        from ..models.version_view import VersionView # noqa: PLC0415
        d = dict(src_dict)
        archived = d.pop("archived")

        description = d.pop("description")

        display_name = d.pop("display_name")

        def _parse_draft(data: object) -> DraftView | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = DraftView.from_dict(data)



                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DraftView | None, data)

        draft = _parse_draft(d.pop("draft"))


        id = UUID(d.pop("id"))




        name = d.pop("name")

        def _parse_published(data: object) -> None | VersionView:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                published_type_0 = VersionView.from_dict(data)



                return published_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | VersionView, data)

        published = _parse_published(d.pop("published"))


        def _parse_published_document(data: object) -> AgentDocument | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                published_document_type_0 = AgentDocument.from_dict(data)



                return published_document_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentDocument | None, data)

        published_document = _parse_published_document(d.pop("published_document"))


        status = StudioAgentViewStatus(d.pop("status"))




        versions = []
        _versions = d.pop("versions")
        for versions_item_data in (_versions):
            versions_item = VersionView.from_dict(versions_item_data)



            versions.append(versions_item)


        studio_agent_view = cls(
            archived=archived,
            description=description,
            display_name=display_name,
            draft=draft,
            id=id,
            name=name,
            published=published,
            published_document=published_document,
            status=status,
            versions=versions,
        )


        studio_agent_view.additional_properties = d
        return studio_agent_view

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
