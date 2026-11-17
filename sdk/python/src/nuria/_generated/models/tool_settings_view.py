from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.tool_settings_view_search_provider import ToolSettingsViewSearchProvider
from ..types import UNSET, Unset
from typing import cast
import datetime






T = TypeVar("T", bound="ToolSettingsView")



@_attrs_define
class ToolSettingsView:
    """ 
        Attributes:
            has_key (bool): A key is saved for the keyed provider (never returned)
            key_fingerprint (None | str):
            search_provider (ToolSettingsViewSearchProvider):
            searxng_url (None | str): Your own SearXNG; none: the one in the stack
            updated_at (datetime.datetime | None):
            web_allowlist (list[str]): When set, pages are read only from these sites
            sandbox (bool | Unset): Run Python, the terminal and files are on Default: False.
     """

    has_key: bool
    key_fingerprint: None | str
    search_provider: ToolSettingsViewSearchProvider
    searxng_url: None | str
    updated_at: datetime.datetime | None
    web_allowlist: list[str]
    sandbox: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        has_key = self.has_key

        key_fingerprint: None | str
        key_fingerprint = self.key_fingerprint

        search_provider = self.search_provider.value

        searxng_url: None | str
        searxng_url = self.searxng_url

        updated_at: None | str
        if isinstance(self.updated_at, datetime.datetime):
            updated_at = self.updated_at.isoformat()
        else:
            updated_at = self.updated_at

        web_allowlist = self.web_allowlist



        sandbox = self.sandbox


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "has_key": has_key,
            "key_fingerprint": key_fingerprint,
            "search_provider": search_provider,
            "searxng_url": searxng_url,
            "updated_at": updated_at,
            "web_allowlist": web_allowlist,
        })
        if sandbox is not UNSET:
            field_dict["sandbox"] = sandbox

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        has_key = d.pop("has_key")

        def _parse_key_fingerprint(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        key_fingerprint = _parse_key_fingerprint(d.pop("key_fingerprint"))


        search_provider = ToolSettingsViewSearchProvider(d.pop("search_provider"))




        def _parse_searxng_url(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        searxng_url = _parse_searxng_url(d.pop("searxng_url"))


        def _parse_updated_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                updated_at_type_0 = datetime.datetime.fromisoformat(data)



                return updated_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        updated_at = _parse_updated_at(d.pop("updated_at"))


        web_allowlist = cast(list[str], d.pop("web_allowlist"))


        sandbox = d.pop("sandbox", UNSET)

        tool_settings_view = cls(
            has_key=has_key,
            key_fingerprint=key_fingerprint,
            search_provider=search_provider,
            searxng_url=searxng_url,
            updated_at=updated_at,
            web_allowlist=web_allowlist,
            sandbox=sandbox,
        )


        tool_settings_view.additional_properties = d
        return tool_settings_view

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
