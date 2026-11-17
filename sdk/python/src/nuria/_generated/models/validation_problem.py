from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.validation_issue import ValidationIssue





T = TypeVar("T", bound="ValidationProblem")



@_attrs_define
class ValidationProblem:
    """ A 422. When the request's own fields didn't validate, `errors` says where and why;
    other 422s say why in fields of their own (a limit's `field` and `maximum`, a skill's
    `issues`).

        Attributes:
            detail (str): This occurrence, in words for a person
            status (int): The HTTP status code
            title (str): A short summary of the kind of problem
            type_ (str): A URI naming the kind of problem: the field to branch on
            errors (list[ValidationIssue] | None | Unset):
     """

    detail: str
    status: int
    title: str
    type_: str
    errors: list[ValidationIssue] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.validation_issue import ValidationIssue # noqa: PLC0415
        detail = self.detail

        status = self.status

        title = self.title

        type_ = self.type_

        errors: list[dict[str, Any]] | None | Unset
        if isinstance(self.errors, Unset):
            errors = UNSET
        elif isinstance(self.errors, list):
            errors = []
            for errors_type_0_item_data in self.errors:
                errors_type_0_item = errors_type_0_item_data.to_dict()
                errors.append(errors_type_0_item)


        else:
            errors = self.errors


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "detail": detail,
            "status": status,
            "title": title,
            "type": type_,
        })
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.validation_issue import ValidationIssue # noqa: PLC0415
        d = dict(src_dict)
        detail = d.pop("detail")

        status = d.pop("status")

        title = d.pop("title")

        type_ = d.pop("type")

        def _parse_errors(data: object) -> list[ValidationIssue] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                errors_type_0 = []
                _errors_type_0 = data
                for errors_type_0_item_data in (_errors_type_0):
                    errors_type_0_item = ValidationIssue.from_dict(errors_type_0_item_data)



                    errors_type_0.append(errors_type_0_item)

                return errors_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ValidationIssue] | None | Unset, data)

        errors = _parse_errors(d.pop("errors", UNSET))


        validation_problem = cls(
            detail=detail,
            status=status,
            title=title,
            type_=type_,
            errors=errors,
        )


        validation_problem.additional_properties = d
        return validation_problem

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
