from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.case import Case
  from ..models.test_result_view import TestResultView





T = TypeVar("T", bound="CaseView")



@_attrs_define
class CaseView:
    """ 
        Attributes:
            case (Case):
            from_run (None | UUID):
            id (UUID):
            result (None | TestResultView): Its latest result, current or not
            updated_at (datetime.datetime):
     """

    case: Case
    from_run: None | UUID
    id: UUID
    result: None | TestResultView
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.case import Case # noqa: PLC0415
        from ..models.test_result_view import TestResultView # noqa: PLC0415
        case = self.case.to_dict()

        from_run: None | str
        if isinstance(self.from_run, UUID):
            from_run = str(self.from_run)
        else:
            from_run = self.from_run

        id = str(self.id)

        result: dict[str, Any] | None
        if isinstance(self.result, TestResultView):
            result = self.result.to_dict()
        else:
            result = self.result

        updated_at = self.updated_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "case": case,
            "from_run": from_run,
            "id": id,
            "result": result,
            "updated_at": updated_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.case import Case # noqa: PLC0415
        from ..models.test_result_view import TestResultView # noqa: PLC0415
        d = dict(src_dict)
        case = Case.from_dict(d.pop("case"))




        def _parse_from_run(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                from_run_type_0 = UUID(data)



                return from_run_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        from_run = _parse_from_run(d.pop("from_run"))


        id = UUID(d.pop("id"))




        def _parse_result(data: object) -> None | TestResultView:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_0 = TestResultView.from_dict(data)



                return result_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TestResultView, data)

        result = _parse_result(d.pop("result"))


        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))




        case_view = cls(
            case=case,
            from_run=from_run,
            id=id,
            result=result,
            updated_at=updated_at,
        )


        case_view.additional_properties = d
        return case_view

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
