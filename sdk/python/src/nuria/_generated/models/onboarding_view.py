from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.onboarding_view_next_type_0 import OnboardingViewNextType0
from typing import cast

if TYPE_CHECKING:
  from ..models.guide_agent_view import GuideAgentView
  from ..models.step import Step
  from ..models.tried import Tried





T = TypeVar("T", bound="OnboardingView")



@_attrs_define
class OnboardingView:
    """ 
        Attributes:
            agent (GuideAgentView | None): The agent built in the guide
            dismissed (bool):
            finished (bool):
            next_ (None | OnboardingViewNextType0): The first step neither done nor skipped
            steps (list[Step]):
            tried (Tried):
     """

    agent: GuideAgentView | None
    dismissed: bool
    finished: bool
    next_: None | OnboardingViewNextType0
    steps: list[Step]
    tried: Tried
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.guide_agent_view import GuideAgentView # noqa: PLC0415
        from ..models.step import Step # noqa: PLC0415
        from ..models.tried import Tried # noqa: PLC0415
        agent: dict[str, Any] | None
        if isinstance(self.agent, GuideAgentView):
            agent = self.agent.to_dict()
        else:
            agent = self.agent

        dismissed = self.dismissed

        finished = self.finished

        next_: None | str
        if isinstance(self.next_, OnboardingViewNextType0):
            next_ = self.next_.value
        else:
            next_ = self.next_

        steps = []
        for steps_item_data in self.steps:
            steps_item = steps_item_data.to_dict()
            steps.append(steps_item)



        tried = self.tried.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "agent": agent,
            "dismissed": dismissed,
            "finished": finished,
            "next": next_,
            "steps": steps,
            "tried": tried,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.guide_agent_view import GuideAgentView # noqa: PLC0415
        from ..models.step import Step # noqa: PLC0415
        from ..models.tried import Tried # noqa: PLC0415
        d = dict(src_dict)
        def _parse_agent(data: object) -> GuideAgentView | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                agent_type_0 = GuideAgentView.from_dict(data)



                return agent_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GuideAgentView | None, data)

        agent = _parse_agent(d.pop("agent"))


        dismissed = d.pop("dismissed")

        finished = d.pop("finished")

        def _parse_next_(data: object) -> None | OnboardingViewNextType0:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                next_type_0 = OnboardingViewNextType0(data)



                return next_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OnboardingViewNextType0, data)

        next_ = _parse_next_(d.pop("next"))


        steps = []
        _steps = d.pop("steps")
        for steps_item_data in (_steps):
            steps_item = Step.from_dict(steps_item_data)



            steps.append(steps_item)


        tried = Tried.from_dict(d.pop("tried"))




        onboarding_view = cls(
            agent=agent,
            dismissed=dismissed,
            finished=finished,
            next_=next_,
            steps=steps,
            tried=tried,
        )


        onboarding_view.additional_properties = d
        return onboarding_view

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
