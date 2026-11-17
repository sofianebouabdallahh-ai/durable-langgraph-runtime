from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.tool_settings_update_search_provider_type_0 import ToolSettingsUpdateSearchProviderType0
from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="ToolSettingsUpdate")



@_attrs_define
class ToolSettingsUpdate:
    """ 
        Attributes:
            api_key (None | str | Unset):
            search_provider (None | ToolSettingsUpdateSearchProviderType0 | Unset):
            searxng_url (None | str | Unset):
            web_allowlist (list[str] | None | Unset):
     """

    api_key: None | str | Unset = UNSET
    search_provider: None | ToolSettingsUpdateSearchProviderType0 | Unset = UNSET
    searxng_url: None | str | Unset = UNSET
    web_allowlist: list[str] | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        api_key: None | str | Unset
        if isinstance(self.api_key, Unset):
            api_key = UNSET
        else:
            api_key = self.api_key

        search_provider: None | str | Unset
        if isinstance(self.search_provider, Unset):
            search_provider = UNSET
        elif isinstance(self.search_provider, ToolSettingsUpdateSearchProviderType0):
            search_provider = self.search_provider.value
        else:
            search_provider = self.search_provider

        searxng_url: None | str | Unset
        if isinstance(self.searxng_url, Unset):
            searxng_url = UNSET
        else:
            searxng_url = self.searxng_url

        web_allowlist: list[str] | None | Unset
        if isinstance(self.web_allowlist, Unset):
            web_allowlist = UNSET
        elif isinstance(self.web_allowlist, list):
            web_allowlist = self.web_allowlist


        else:
            web_allowlist = self.web_allowlist


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if api_key is not UNSET:
            field_dict["api_key"] = api_key
        if search_provider is not UNSET:
            field_dict["search_provider"] = search_provider
        if searxng_url is not UNSET:
            field_dict["searxng_url"] = searxng_url
        if web_allowlist is not UNSET:
            field_dict["web_allowlist"] = web_allowlist

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_api_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        api_key = _parse_api_key(d.pop("api_key", UNSET))


        def _parse_search_provider(data: object) -> None | ToolSettingsUpdateSearchProviderType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                search_provider_type_0 = ToolSettingsUpdateSearchProviderType0(data)



                return search_provider_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ToolSettingsUpdateSearchProviderType0 | Unset, data)

        search_provider = _parse_search_provider(d.pop("search_provider", UNSET))


        def _parse_searxng_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        searxng_url = _parse_searxng_url(d.pop("searxng_url", UNSET))


        def _parse_web_allowlist(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                web_allowlist_type_0 = cast(list[str], data)

                return web_allowlist_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        web_allowlist = _parse_web_allowlist(d.pop("web_allowlist", UNSET))


        tool_settings_update = cls(
            api_key=api_key,
            search_provider=search_provider,
            searxng_url=searxng_url,
            web_allowlist=web_allowlist,
        )

        return tool_settings_update

