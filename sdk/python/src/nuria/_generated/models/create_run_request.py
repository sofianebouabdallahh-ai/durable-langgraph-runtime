from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.create_run_request_input import CreateRunRequestInput
  from ..models.create_run_request_options_type_0 import CreateRunRequestOptionsType0





T = TypeVar("T", bound="CreateRunRequest")



@_attrs_define
class CreateRunRequest:
    """ 
        Attributes:
            graph (str):
            input_ (CreateRunRequestInput):
            options (CreateRunRequestOptionsType0 | None | Unset):
     """

    graph: str
    input_: CreateRunRequestInput
    options: CreateRunRequestOptionsType0 | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.create_run_request_input import CreateRunRequestInput # noqa: PLC0415
        from ..models.create_run_request_options_type_0 import CreateRunRequestOptionsType0 # noqa: PLC0415
        graph = self.graph

        input_ = self.input_.to_dict()

        options: dict[str, Any] | None | Unset
        if isinstance(self.options, Unset):
            options = UNSET
        elif isinstance(self.options, CreateRunRequestOptionsType0):
            options = self.options.to_dict()
        else:
            options = self.options


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "graph": graph,
            "input": input_,
        })
        if options is not UNSET:
            field_dict["options"] = options

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.create_run_request_input import CreateRunRequestInput # noqa: PLC0415
        from ..models.create_run_request_options_type_0 import CreateRunRequestOptionsType0 # noqa: PLC0415
        d = dict(src_dict)
        graph = d.pop("graph")

        input_ = CreateRunRequestInput.from_dict(d.pop("input"))




        def _parse_options(data: object) -> CreateRunRequestOptionsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                options_type_0 = CreateRunRequestOptionsType0.from_dict(data)



                return options_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CreateRunRequestOptionsType0 | None | Unset, data)

        options = _parse_options(d.pop("options", UNSET))


        create_run_request = cls(
            graph=graph,
            input_=input_,
            options=options,
        )

        return create_run_request

