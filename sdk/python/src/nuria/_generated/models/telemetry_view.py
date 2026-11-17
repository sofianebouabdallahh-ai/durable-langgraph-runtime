from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.telemetry_view_fields import TelemetryViewFields
  from ..models.telemetry_view_report import TelemetryViewReport





T = TypeVar("T", bound="TelemetryView")



@_attrs_define
class TelemetryView:
    """ 
        Attributes:
            fields (TelemetryViewFields): What each count is: never content, names or keys
            report (TelemetryViewReport): Exactly what would be attached
            sharing (bool): Usage counts are attached to feedback you send (off by default)
     """

    fields: TelemetryViewFields
    report: TelemetryViewReport
    sharing: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.telemetry_view_fields import TelemetryViewFields # noqa: PLC0415
        from ..models.telemetry_view_report import TelemetryViewReport # noqa: PLC0415
        fields = self.fields.to_dict()

        report = self.report.to_dict()

        sharing = self.sharing


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "fields": fields,
            "report": report,
            "sharing": sharing,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.telemetry_view_fields import TelemetryViewFields # noqa: PLC0415
        from ..models.telemetry_view_report import TelemetryViewReport # noqa: PLC0415
        d = dict(src_dict)
        fields = TelemetryViewFields.from_dict(d.pop("fields"))




        report = TelemetryViewReport.from_dict(d.pop("report"))




        sharing = d.pop("sharing")

        telemetry_view = cls(
            fields=fields,
            report=report,
            sharing=sharing,
        )


        telemetry_view.additional_properties = d
        return telemetry_view

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
