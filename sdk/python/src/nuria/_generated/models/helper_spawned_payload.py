from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from uuid import UUID






T = TypeVar("T", bound="HelperSpawnedPayload")



@_attrs_define
class HelperSpawnedPayload:
    """ 
        Attributes:
            agent (str):
            handle (UUID):
            task (str):
            worker (str): The worker the helper runs in (the main run's)
     """

    agent: str
    handle: UUID
    task: str
    worker: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        handle = str(self.handle)

        task = self.task

        worker = self.worker


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "handle": handle,
            "task": task,
            "worker": worker,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        handle = UUID(d.pop("handle"))




        task = d.pop("task")

        worker = d.pop("worker")

        helper_spawned_payload = cls(
            agent=agent,
            handle=handle,
            task=task,
            worker=worker,
        )


        helper_spawned_payload.additional_properties = d
        return helper_spawned_payload

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
