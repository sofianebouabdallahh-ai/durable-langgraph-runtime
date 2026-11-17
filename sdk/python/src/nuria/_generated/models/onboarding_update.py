from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="OnboardingUpdate")



@_attrs_define
class OnboardingUpdate:
    """ 
        Attributes:
            agent_id (None | Unset | UUID): Make this the guide's agent
            dismissed (bool | None | Unset):
            restart (bool | Unset):  Default: False.
            skip_model (bool | None | Unset): Use the demo model for now
     """

    agent_id: None | Unset | UUID = UNSET
    dismissed: bool | None | Unset = UNSET
    restart: bool | Unset = False
    skip_model: bool | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        agent_id: None | str | Unset
        if isinstance(self.agent_id, Unset):
            agent_id = UNSET
        elif isinstance(self.agent_id, UUID):
            agent_id = str(self.agent_id)
        else:
            agent_id = self.agent_id

        dismissed: bool | None | Unset
        if isinstance(self.dismissed, Unset):
            dismissed = UNSET
        else:
            dismissed = self.dismissed

        restart = self.restart

        skip_model: bool | None | Unset
        if isinstance(self.skip_model, Unset):
            skip_model = UNSET
        else:
            skip_model = self.skip_model


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if dismissed is not UNSET:
            field_dict["dismissed"] = dismissed
        if restart is not UNSET:
            field_dict["restart"] = restart
        if skip_model is not UNSET:
            field_dict["skip_model"] = skip_model

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_agent_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                agent_id_type_0 = UUID(data)



                return agent_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        agent_id = _parse_agent_id(d.pop("agent_id", UNSET))


        def _parse_dismissed(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        dismissed = _parse_dismissed(d.pop("dismissed", UNSET))


        restart = d.pop("restart", UNSET)

        def _parse_skip_model(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        skip_model = _parse_skip_model(d.pop("skip_model", UNSET))


        onboarding_update = cls(
            agent_id=agent_id,
            dismissed=dismissed,
            restart=restart,
            skip_model=skip_model,
        )

        return onboarding_update

