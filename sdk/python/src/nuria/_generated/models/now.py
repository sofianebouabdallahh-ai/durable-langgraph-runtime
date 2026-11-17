from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.waiting import Waiting





T = TypeVar("T", bound="Now")



@_attrs_define
class Now:
    """ 
        Attributes:
            queued (int):
            running (int):
            spend_today (float):
            waiting (list[Waiting]):
            waiting_approval (int):
     """

    queued: int
    running: int
    spend_today: float
    waiting: list[Waiting]
    waiting_approval: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.waiting import Waiting # noqa: PLC0415
        queued = self.queued

        running = self.running

        spend_today = self.spend_today

        waiting = []
        for waiting_item_data in self.waiting:
            waiting_item = waiting_item_data.to_dict()
            waiting.append(waiting_item)



        waiting_approval = self.waiting_approval


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "queued": queued,
            "running": running,
            "spend_today": spend_today,
            "waiting": waiting,
            "waiting_approval": waiting_approval,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.waiting import Waiting # noqa: PLC0415
        d = dict(src_dict)
        queued = d.pop("queued")

        running = d.pop("running")

        spend_today = d.pop("spend_today")

        waiting = []
        _waiting = d.pop("waiting")
        for waiting_item_data in (_waiting):
            waiting_item = Waiting.from_dict(waiting_item_data)



            waiting.append(waiting_item)


        waiting_approval = d.pop("waiting_approval")

        now = cls(
            queued=queued,
            running=running,
            spend_today=spend_today,
            waiting=waiting,
            waiting_approval=waiting_approval,
        )


        now.additional_properties = d
        return now

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
