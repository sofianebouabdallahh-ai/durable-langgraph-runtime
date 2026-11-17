from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.approval_edits_args_type_0 import ApprovalEditsArgsType0





T = TypeVar("T", bound="ApprovalEdits")



@_attrs_define
class ApprovalEdits:
    """ 
        Attributes:
            args (ApprovalEditsArgsType0 | None | Unset): Replacement tool arguments (re-validated before use)
     """

    args: ApprovalEditsArgsType0 | None | Unset = UNSET





    def to_dict(self) -> dict[str, Any]:
        from ..models.approval_edits_args_type_0 import ApprovalEditsArgsType0 # noqa: PLC0415
        args: dict[str, Any] | None | Unset
        if isinstance(self.args, Unset):
            args = UNSET
        elif isinstance(self.args, ApprovalEditsArgsType0):
            args = self.args.to_dict()
        else:
            args = self.args


        field_dict: dict[str, Any] = {}

        field_dict.update({
        })
        if args is not UNSET:
            field_dict["args"] = args

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.approval_edits_args_type_0 import ApprovalEditsArgsType0 # noqa: PLC0415
        d = dict(src_dict)
        def _parse_args(data: object) -> ApprovalEditsArgsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                args_type_0 = ApprovalEditsArgsType0.from_dict(data)



                return args_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ApprovalEditsArgsType0 | None | Unset, data)

        args = _parse_args(d.pop("args", UNSET))


        approval_edits = cls(
            args=args,
        )

        return approval_edits

