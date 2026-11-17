from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.test_result_view_status import TestResultViewStatus
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.check_view import CheckView





T = TypeVar("T", bound="TestResultView")



@_attrs_define
class TestResultView:
    """ 
        Attributes:
            checks (list[CheckView]):
            created_at (datetime.datetime):
            current (bool): On this draft, and the case as it is now
            finished_at (datetime.datetime | None):
            run_id (UUID):
            session_id (None | UUID): Its test chat, to see what happened
            status (TestResultViewStatus):
     """

    checks: list[CheckView]
    created_at: datetime.datetime
    current: bool
    finished_at: datetime.datetime | None
    run_id: UUID
    session_id: None | UUID
    status: TestResultViewStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.check_view import CheckView # noqa: PLC0415
        checks = []
        for checks_item_data in self.checks:
            checks_item = checks_item_data.to_dict()
            checks.append(checks_item)



        created_at = self.created_at.isoformat()

        current = self.current

        finished_at: None | str
        if isinstance(self.finished_at, datetime.datetime):
            finished_at = self.finished_at.isoformat()
        else:
            finished_at = self.finished_at

        run_id = str(self.run_id)

        session_id: None | str
        if isinstance(self.session_id, UUID):
            session_id = str(self.session_id)
        else:
            session_id = self.session_id

        status = self.status.value


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "checks": checks,
            "created_at": created_at,
            "current": current,
            "finished_at": finished_at,
            "run_id": run_id,
            "session_id": session_id,
            "status": status,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.check_view import CheckView # noqa: PLC0415
        d = dict(src_dict)
        checks = []
        _checks = d.pop("checks")
        for checks_item_data in (_checks):
            checks_item = CheckView.from_dict(checks_item_data)



            checks.append(checks_item)


        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        current = d.pop("current")

        def _parse_finished_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                finished_at_type_0 = datetime.datetime.fromisoformat(data)



                return finished_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        finished_at = _parse_finished_at(d.pop("finished_at"))


        run_id = UUID(d.pop("run_id"))




        def _parse_session_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                session_id_type_0 = UUID(data)



                return session_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        session_id = _parse_session_id(d.pop("session_id"))


        status = TestResultViewStatus(d.pop("status"))




        test_result_view = cls(
            checks=checks,
            created_at=created_at,
            current=current,
            finished_at=finished_at,
            run_id=run_id,
            session_id=session_id,
            status=status,
        )


        test_result_view.additional_properties = d
        return test_result_view

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
