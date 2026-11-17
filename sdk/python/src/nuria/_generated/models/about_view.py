from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="AboutView")



@_attrs_define
class AboutView:
    """ What the UI shows about this installation; nothing secret (no keys, no URLs).

        Attributes:
            chat_model (None | str): The chat role's model, when configured
            demo_model (bool): The offline demo model (MODEL_PROVIDER=scripted)
            model_provider (str):
            version (None | str):
            dashboard_url (None | str | Unset): The Grafana dashboard
            retention_days (int | Unset): A run that ended this many days ago loses its details (H10); 0: never Default: 90.
            trace_ui_url (None | str | Unset): Grafana: a run's trace (Tempo) and its log lines (Loki) open in Explore
            tracing (bool | Unset): Traces are exported (--observability) Default: False.
     """

    chat_model: None | str
    demo_model: bool
    model_provider: str
    version: None | str
    dashboard_url: None | str | Unset = UNSET
    retention_days: int | Unset = 90
    trace_ui_url: None | str | Unset = UNSET
    tracing: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        chat_model: None | str
        chat_model = self.chat_model

        demo_model = self.demo_model

        model_provider = self.model_provider

        version: None | str
        version = self.version

        dashboard_url: None | str | Unset
        if isinstance(self.dashboard_url, Unset):
            dashboard_url = UNSET
        else:
            dashboard_url = self.dashboard_url

        retention_days = self.retention_days

        trace_ui_url: None | str | Unset
        if isinstance(self.trace_ui_url, Unset):
            trace_ui_url = UNSET
        else:
            trace_ui_url = self.trace_ui_url

        tracing = self.tracing


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "chat_model": chat_model,
            "demo_model": demo_model,
            "model_provider": model_provider,
            "version": version,
        })
        if dashboard_url is not UNSET:
            field_dict["dashboard_url"] = dashboard_url
        if retention_days is not UNSET:
            field_dict["retention_days"] = retention_days
        if trace_ui_url is not UNSET:
            field_dict["trace_ui_url"] = trace_ui_url
        if tracing is not UNSET:
            field_dict["tracing"] = tracing

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_chat_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        chat_model = _parse_chat_model(d.pop("chat_model"))


        demo_model = d.pop("demo_model")

        model_provider = d.pop("model_provider")

        def _parse_version(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        version = _parse_version(d.pop("version"))


        def _parse_dashboard_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dashboard_url = _parse_dashboard_url(d.pop("dashboard_url", UNSET))


        retention_days = d.pop("retention_days", UNSET)

        def _parse_trace_ui_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        trace_ui_url = _parse_trace_ui_url(d.pop("trace_ui_url", UNSET))


        tracing = d.pop("tracing", UNSET)

        about_view = cls(
            chat_model=chat_model,
            demo_model=demo_model,
            model_provider=model_provider,
            version=version,
            dashboard_url=dashboard_url,
            retention_days=retention_days,
            trace_ui_url=trace_ui_url,
            tracing=tracing,
        )


        about_view.additional_properties = d
        return about_view

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
